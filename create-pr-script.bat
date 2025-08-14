@echo off
echo Creating Pull Request for AI Review Test...
echo.
echo First, authenticate with GitHub:
"C:\Program Files\GitHub CLI\gh.exe" auth login

echo.
echo Creating PR from test/ai-review branch to main:
"C:\Program Files\GitHub CLI\gh.exe" pr create --base main --head test/ai-review --title "Test: AI Code Review with Vulnerable Code" --body "## 🤖 Testing AI Code Review Features

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
- Character encoding errors
- Missing Turkish characters

#### 🐛 Code Quality:
- Missing error handling
- Type safety issues
- Unused variables
- Accessibility problems

### AI Reviewers:
- [ ] Gemini Code Review
- [ ] GitHub Copilot
- [ ] CodeQL Security Analysis
- [ ] Basic Linting

Let's see what our AI tools can catch! 🎯"

echo.
echo Pull Request created successfully!
echo Check: https://github.com/shaptina/projem/pulls
pause