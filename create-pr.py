#!/usr/bin/env python3
"""
GitHub Pull Request Creator
"""

import requests
import json

# GitHub API configuration
GITHUB_TOKEN = "[YOUR_GITHUB_TOKEN_HERE]"
REPO_OWNER = "shaptina"
REPO_NAME = "projem"
BASE_BRANCH = "main"
HEAD_BRANCH = "test/ai-review"

# PR details
PR_TITLE = "Test: AI Code Review with Vulnerable Code"
PR_BODY = """## 🤖 Testing AI Code Review Features

This PR contains intentionally vulnerable code to test our AI review capabilities.

### Test Files Added:
- `apps/api/app/test_review.py` - Python backend with security issues
- `apps/web/src/test-review.tsx` - React frontend with vulnerabilities

### Expected Issues to be Detected:

#### 🔐 Security Issues:
- Hardcoded passwords and API keys
- SQL injection vulnerabilities  
- Command injection risks
- XSS vulnerabilities
- Path traversal issues

#### ⚡ Performance Issues:
- O(n³) complexity algorithms
- Memory leaks
- Infinite loop risks
- Unnecessary re-renders

#### 🇹🇷 Turkish Localization:
- Character encoding errors (nasilsiniz → nasılsınız)
- Missing Turkish characters (Hosgeldiniz → Hoş geldiniz)

#### 🐛 Code Quality:
- Missing error handling
- Type safety issues
- Unused variables
- Accessibility problems

### AI Reviewers Expected:
- [ ] Gemini Code Review (API key required)
- [ ] GitHub Copilot (API key required)
- [ ] CodeQL Security Analysis (Free - will run)
- [ ] Basic Linting (Free - will run)

Let's see what our AI tools can catch! 🎯"""

def create_pull_request():
    """Create a pull request using GitHub API"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls"
    
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    data = {
        "title": PR_TITLE,
        "body": PR_BODY,
        "head": HEAD_BRANCH,
        "base": BASE_BRANCH
    }
    
    print("Creating Pull Request...")
    response = requests.post(url, headers=headers, json=data)
    
    if response.status_code == 201:
        pr_data = response.json()
        print(f"SUCCESS: Pull Request created successfully!")
        print(f"PR Number: #{pr_data['number']}")
        print(f"PR URL: {pr_data['html_url']}")
        return pr_data
    elif response.status_code == 422:
        error_data = response.json()
        if "already exists" in str(error_data):
            print("WARNING: Pull Request already exists!")
            # Get existing PR
            pulls_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls?head={REPO_OWNER}:{HEAD_BRANCH}&base={BASE_BRANCH}"
            existing_pr = requests.get(pulls_url, headers=headers).json()
            if existing_pr:
                print(f"Existing PR URL: {existing_pr[0]['html_url']}")
        else:
            print(f"ERROR: {error_data}")
    else:
        print(f"ERROR: Failed to create PR: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    create_pull_request()