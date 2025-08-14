#!/usr/bin/env python3
"""
Google Gemini Code Review Script for GitHub Actions
"""

import os
import json
import sys
from pathlib import Path
import google.generativeai as genai
import git
import requests
from typing import List, Dict, Any

class GeminiCodeReviewer:
    def __init__(self):
        # Configure Gemini
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
        self.model = genai.GenerativeModel('models/gemini-2.0-flash')
        self.repo = git.Repo(".")
        self.github_token = os.environ.get("GITHUB_TOKEN")
        self.pr_number = os.environ.get("PR_NUMBER")
        
    def get_changed_files(self) -> List[Dict[str, Any]]:
        """Get list of changed files in the PR or commit"""
        changed_files = []
        
        try:
            # For PRs, compare with base branch
            if self.pr_number:
                base_ref = os.environ.get("GITHUB_BASE_REF", "main")
                diff = self.repo.git.diff(f"origin/{base_ref}...HEAD", name_status=True)
            else:
                # For pushes, compare with previous commit
                diff = self.repo.git.diff("HEAD~1..HEAD", name_status=True)
            
            for line in diff.split('\n'):
                if line:
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        status, filepath = parts[0], parts[1]
                        if Path(filepath).exists():
                            try:
                                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                                    content = f.read()
                                changed_files.append({
                                    'path': filepath,
                                    'status': status,
                                    'content': content[:3000]  # Limit for token size
                                })
                            except:
                                continue
        except Exception as e:
            print(f"Error getting changed files: {e}")
        
        return changed_files
    
    def analyze_code(self, files: List[Dict[str, Any]]) -> str:
        """Send code to Gemini for analysis"""
        if not files:
            return "No files to analyze"
        
        # Prepare prompt for Gemini
        prompt = """You are reviewing code for a FreeCAD-based CNC/CAM/CAD production platform with Turkish UI.
        
Please analyze the following code changes for:
1. 🔒 Security vulnerabilities (SQL injection, XSS, hardcoded secrets)
2. ⚡ Performance issues (inefficient algorithms, memory leaks)
3. 🐛 Potential bugs (null checks, error handling, edge cases)
4. 📝 Code quality (naming, structure, best practices)
5. 🇹🇷 Turkish localization issues (character encoding, translations)

Changed files:

"""
        
        for file in files[:5]:  # Limit to 5 files
            prompt += f"\n📄 File: {file['path']} (Status: {file['status']})\n"
            prompt += f"```{Path(file['path']).suffix[1:]}\n"
            prompt += file['content']
            prompt += "\n```\n"
        
        prompt += "\nProvide specific, actionable feedback. Use Turkish where appropriate. Format as markdown."
        
        try:
            # Call Gemini API
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Error analyzing code: {str(e)}"
    
    def post_review_comment(self, review_text: str):
        """Post review as GitHub PR comment"""
        if not self.pr_number:
            print("No PR number, outputting to console")
            print("\n" + "="*50)
            print("GEMINI CODE REVIEW")
            print("="*50)
            print(review_text)
            return
        
        try:
            repo = os.environ.get("GITHUB_REPOSITORY")
            url = f"https://api.github.com/repos/{repo}/issues/{self.pr_number}/comments"
            
            headers = {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json"
            }
            
            data = {
                "body": f"""## 🤖 Gemini Code Review

{review_text}

---
*Reviewed by Google Gemini AI*"""
            }
            
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 201:
                print("✅ Gemini review posted successfully!")
            else:
                print(f"❌ Failed to post review: {response.status_code}")
                print(response.text)
        except Exception as e:
            print(f"Error posting comment: {e}")
    
    def run(self):
        """Main execution"""
        print("🔍 Gemini Code Reviewer starting...")
        
        # Get changed files
        changed_files = self.get_changed_files()
        print(f"📁 Found {len(changed_files)} changed files")
        
        if not changed_files:
            print("✅ No files to review")
            return
        
        # Analyze with Gemini
        print("🤖 Analyzing with Google Gemini...")
        review = self.analyze_code(changed_files)
        
        # Post review
        self.post_review_comment(review)
        
        # Save to file
        with open("gemini-review.md", "w", encoding="utf-8") as f:
            f.write(review)
        
        print("✅ Gemini review complete!")

if __name__ == "__main__":
    try:
        if not os.environ.get("GEMINI_API_KEY"):
            print("⚠️ GEMINI_API_KEY not set, skipping review")
            sys.exit(0)
        
        reviewer = GeminiCodeReviewer()
        reviewer.run()
    except Exception as e:
        print(f"❌ Error: {e}")
        # Don't fail the workflow
        sys.exit(0)