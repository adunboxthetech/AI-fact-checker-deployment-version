# Vercel Deployment Guide

## Prerequisites
1. Install Vercel CLI: `npm i -g vercel`
2. Make sure you have a Vercel account

## Environment Variables
Before deploying, you need to set up your environment variables in Vercel:

1. Go to your Vercel dashboard
2. Create a new project
3. In the project settings, go to "Environment Variables"
4. Add your `PERPLEXITY_API_KEY` variable

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
