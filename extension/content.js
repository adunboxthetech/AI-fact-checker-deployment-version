(() => {
  if (window.__aiFactCheckerContentLoaded) return;
  window.__aiFactCheckerContentLoaded = true;

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "EXTRACT_VISIBLE_POST") {
      return false;
    }

    try {
      const post = extractVisiblePost();
      if (!post) {
        sendResponse({ ok: false, error: "No visible post was found." });
        return false;
      }
      sendResponse({ ok: true, post });
    } catch (error) {
      sendResponse({ ok: false, error: error.message });
    }
    return false;
  });

  function extractVisiblePost() {
    const platform = detectPlatform();
    const candidates = collectCandidates(platform)
      .map((element) => buildCandidate(element, platform))
      .filter(Boolean)
      .sort((a, b) => b.score - a.score);

    const best = candidates[0] || buildCandidate(document.body, platform);
    if (!best) return null;

    return {
      text: best.text,
      title: document.title || "",
      author: best.author || "",
      platform,
      page_url: location.href,
      post_url: best.postUrl || location.href,
      url: best.postUrl || location.href,
      image_urls: best.imageUrls,
      has_visible_media: best.hasVisibleMedia,
      extraction_method: best.method
    };
  }

  function detectPlatform() {
    const host = location.hostname.replace(/^www\./, "").toLowerCase();
    if (host === "x.com" || host.endsWith(".x.com") || host.includes("twitter.com")) return "x.com";
    if (host.includes("reddit.com")) return "reddit";
    if (host.includes("linkedin.com")) return "linkedin";
    if (host.includes("facebook.com")) return "facebook";
    if (host.includes("instagram.com")) return "instagram";
    if (host.includes("threads.net")) return "threads";
    if (host.includes("youtube.com") || host.includes("youtu.be")) return "youtube";
    return host || "web";
  }

  function collectCandidates(platform) {
    const selectorsByPlatform = {
      "x.com": ["article", "[data-testid='tweet']"],
      reddit: ["shreddit-post", "[data-testid='post-container']", "article"],
      linkedin: [".feed-shared-update-v2", "[data-urn*='activity']", "article"],
      facebook: ["[role='article']", "[data-pagelet^='FeedUnit_']"],
      instagram: ["article", "main article"],
      threads: ["[data-pressable-container='true']", "article"],
      youtube: ["ytd-watch-metadata", "ytd-rich-item-renderer", "ytd-video-renderer", "ytd-comment-thread-renderer"]
    };
    const selectors = selectorsByPlatform[platform] || ["article", "main", "section", "[role='article']"];
    const elements = new Set();

    for (const selector of selectors) {
      document.querySelectorAll(selector).forEach((element) => elements.add(element));
    }

    if (!elements.size) {
      document.querySelectorAll("article, main, section, div").forEach((element) => {
        const rect = element.getBoundingClientRect();
        if (rect.width >= 280 && rect.height >= 80 && rect.height <= window.innerHeight * 1.8) {
          elements.add(element);
        }
      });
    }

    return Array.from(elements).filter(isVisible);
  }

  function buildCandidate(element, platform) {
    const rect = element.getBoundingClientRect();
    if (!intersectsViewport(rect)) return null;

    const text = extractMeaningfulText(element);
    const imageUrls = extractImageUrls(element);
    const hasVisibleMedia = imageUrls.length > 0 || Boolean(element.querySelector("video, canvas, picture"));
    if (text.length < 30 && !hasVisibleMedia) return null;

    const centerX = window.innerWidth / 2;
    const centerY = window.innerHeight / 2;
    const elementCenterX = rect.left + rect.width / 2;
    const elementCenterY = rect.top + rect.height / 2;
    const distance = Math.hypot(centerX - elementCenterX, centerY - elementCenterY);
    const viewportDiagonal = Math.hypot(window.innerWidth, window.innerHeight);
    const centerScore = 1 - Math.min(distance / viewportDiagonal, 1);
    const textScore = Math.min(text.length / 900, 1);
    const semanticScore = semanticBoost(element, platform);
    const imageScore = hasVisibleMedia ? 0.12 : 0;

    return {
      element,
      text: text.slice(0, 9000),
      imageUrls,
      hasVisibleMedia,
      postUrl: findPostUrl(element),
      author: findAuthor(element),
      method: methodName(element, platform),
      score: centerScore * 0.58 + textScore * 0.24 + semanticScore + imageScore
    };
  }

  function isVisible(element) {
    const style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) {
      return false;
    }
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function intersectsViewport(rect) {
    return rect.bottom > 0 && rect.right > 0 && rect.top < window.innerHeight && rect.left < window.innerWidth;
  }

  function extractMeaningfulText(element) {
    const blockedTags = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "SVG", "BUTTON", "NAV", "HEADER", "FOOTER"]);
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent || blockedTags.has(parent.tagName)) return NodeFilter.FILTER_REJECT;
        if (parent.closest("button, nav, header, footer, [aria-hidden='true']")) {
          return NodeFilter.FILTER_REJECT;
        }
        const value = normalize(node.nodeValue);
        if (!value || value.length < 2) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });

    const parts = [];
    let node;
    while ((node = walker.nextNode())) {
      parts.push(node.nodeValue);
      if (parts.join(" ").length > 10000) break;
    }

    return cleanSocialText(parts.join(" "));
  }

  function cleanSocialText(text) {
    const lines = normalize(text)
      .split(/(?<=[.!?])\s+|\n+/)
      .map((line) => line.trim())
      .filter(Boolean)
      .filter((line) => !/^(like|reply|share|repost|comment|follow|subscribe|views?|likes?|replies)$/i.test(line))
      .filter((line) => !/^\d+([,.]\d+)?[KMB]?\s*(likes?|comments?|shares?|views?|reposts?)$/i.test(line));
    return normalize(lines.join(" "));
  }

  function extractImageUrls(element) {
    const urls = [];
    element.querySelectorAll("img").forEach((img) => {
      const rect = img.getBoundingClientRect();
      if (!intersectsViewport(rect)) return;
      if (rect.width < 90 || rect.height < 90) return;
      const url = img.currentSrc || img.src || "";
      if (!url || url.startsWith("data:") || url.startsWith("blob:")) return;
      urls.push(url);
    });
    return Array.from(new Set(urls)).slice(0, 5);
  }

  function findPostUrl(element) {
    const anchors = Array.from(element.querySelectorAll("a[href]"));
    const patterns = [
      /\/status\/\d+/i,
      /\/comments\/[a-z0-9]+/i,
      /\/posts\/[a-z0-9]+/i,
      /\/activity-\d+/i,
      /\/p\/[a-z0-9_-]+/i,
      /\/watch\?v=/i
    ];

    for (const anchor of anchors) {
      const href = anchor.href || "";
      if (patterns.some((pattern) => pattern.test(href))) {
        return href;
      }
    }
    return "";
  }

  function findAuthor(element) {
    const selectors = [
      "[data-testid='User-Name']",
      ".feed-shared-actor__name",
      "[slot='authorName']",
      "a[role='link'] span",
      "h2",
      "h3"
    ];
    for (const selector of selectors) {
      const match = element.querySelector(selector);
      const text = match ? normalize(match.innerText || match.textContent || "") : "";
      if (text && text.length <= 80) return text;
    }
    return "";
  }

  function semanticBoost(element, platform) {
    const tag = element.tagName.toLowerCase();
    let score = tag === "article" ? 0.16 : 0;
    if (platform === "reddit" && tag === "shreddit-post") score += 0.18;
    if (element.matches("[role='article']")) score += 0.14;
    if (element.matches("[data-testid='tweet'], [data-testid='post-container']")) score += 0.18;
    return score;
  }

  function methodName(element, platform) {
    const tag = element.tagName.toLowerCase();
    if (tag === "article") return `${platform}:article`;
    if (tag === "shreddit-post") return "reddit:shreddit-post";
    if (element.matches("[role='article']")) return `${platform}:role-article`;
    return `${platform}:heuristic`;
  }

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }
})();
