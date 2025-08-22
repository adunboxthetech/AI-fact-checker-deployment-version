# Vercel Deployment Guide

## Prerequisites
1. Install Vercel CLI: `npm i -g vercel`
2. Make sure you have a Vercel account

## Environment Variables
**CRITICAL**: You MUST set up your environment variables in Vercel before deployment:

1. Go to your Vercel dashboard
2. Create a new project
3. In the project settings, go to "Environment Variables"
4. Add your `PERPLEXITY_API_KEY` variable with your actual Perplexity API key
5. Make sure to set it for all environments (Production, Preview, Development)

**If you don't set this environment variable, your deployment will fail with a 500 error!**

## Deployment Steps

### Option 1: Using Vercel CLI
1. Login to Vercel: `vercel login`
2. Deploy: `vercel`
3. Follow the prompts to link to your Vercel account/project

### Option 2: Using GitHub Integration
1. Push your code to GitHub
2. Connect your GitHub repository to Vercel
3. Vercel will automatically deploy on every push

## Files Added for Vercel Deployment
- `vercel.json`: Configuration file for Vercel
- `wsgi.py`: WSGI entry point for the Flask app
- `.gitignore`: Excludes sensitive files and build artifacts
- `DEPLOYMENT.md`: This deployment guide

## Important Notes
- Your Flask app will be available at the Vercel-provided URL
- The API endpoints will be:
  - `GET /` - Health check
  - `GET /health` - Health check
  - `POST /fact-check` - Main fact-checking endpoint
  - `POST /fact-check-image` - Image fact-checking endpoint
- Make sure to set your `PERPLEXITY_API_KEY` environment variable in Vercel dashboard

## Testing After Deployment
Once deployed, test your API endpoints:
```bash
curl https://your-vercel-url.vercel.app/health
```

## Troubleshooting

### If you get a 500 error:
1. **Check environment variables**: Make sure `PERPLEXITY_API_KEY` is set in Vercel dashboard
2. **Check the health endpoint**: Visit `/health` to see if the API key is properly set
3. **Check Vercel logs**: Go to your project dashboard → Functions → View Function Logs

### Common issues:
- **Missing API key**: The most common cause of 500 errors
- **Invalid API key**: Make sure your Perplexity API key is valid
- **Timeout issues**: The function timeout is set to 30 seconds in `vercel.json`
