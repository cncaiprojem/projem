# 🚀 GitHub Repository Setup - ADIM ADIM

## 1️⃣ GitHub'da Repository Oluşturun

### GitHub.com'a gidin ve şu adımları izleyin:

1. **Sağ üst köşede `+` ikonuna tıklayın**
2. **"New repository" seçin**
3. **Şu bilgileri girin:**
   - Repository name: **`projem`**
   - Description: **`FreeCAD-based CNC/CAM/CAD production platform with Turkish UI/UX`**
   - **Public** seçin
   - ⚠️ **IMPORTANT:** 
     - ❌ "Add a README file" işaretlemeyin
     - ❌ "Add .gitignore" işaretlemeyin  
     - ❌ "Choose a license" seçmeyin
4. **"Create repository"** butonuna tıklayın

## 2️⃣ Repository Oluştuktan Sonra

Terminal'de şu komutu çalıştırın:

```bash
# Push kodları GitHub'a
git push -u origin main
```

## 3️⃣ Eğer Authentication Hatası Alırsanız

### Option A: HTTPS with Token
```bash
# Token ile push
git remote set-url origin https://[YOUR_GITHUB_TOKEN]@github.com/kafge/projem.git

# Tekrar push deneyin
git push -u origin main
```

### Option B: SSH Key
```bash
# SSH key oluşturun (yoksa)
ssh-keygen -t ed25519 -C "your-email@example.com"

# SSH key'i GitHub'a ekleyin
# GitHub Settings > SSH and GPG keys > New SSH key

# Remote'u SSH olarak değiştirin
git remote set-url origin git@github.com:kafge/projem.git

# Push
git push -u origin main
```

## 4️⃣ Repository URL'leri

Push başarılı olduktan sonra projeniz şu adreste olacak:

- **HTTPS:** https://github.com/kafge/projem
- **SSH:** git@github.com:kafge/projem.git
- **GitHub CLI:** gh repo view kafge/projem

## 5️⃣ İlk Push Sonrası Yapılacaklar

### README.md Güncelleme
```bash
# README'yi güncelleyin ve push edin
git add README.md
git commit -m "docs: Update README with project details"
git push
```

### GitHub Actions Setup
```bash
# CI/CD pipeline ekleyin
mkdir -p .github/workflows
# workflow dosyalarını ekleyin
git add .github/
git commit -m "ci: Add GitHub Actions workflow"
git push
```

### Branch Protection
1. Settings > Branches
2. Add rule for `main`
3. Enable:
   - Require pull request reviews
   - Require status checks
   - Include administrators

## 📋 Proje Durumu

✅ **Tamamlanan:**
- Git repository initialized
- .gitignore configured
- All files staged
- Initial commit created
- Remote origin set

⏳ **Bekleyen:**
- GitHub'da repository oluşturma (manual)
- Push to GitHub
- CI/CD setup
- Branch protection rules

## 🎯 Quick Commands

```bash
# Status check
git status

# View remote
git remote -v

# Push changes
git push

# Pull latest
git pull

# Create new branch
git checkout -b feature/new-feature

# Switch branches
git checkout main
```

## 🔗 Useful Links

- [GitHub Docs](https://docs.github.com)
- [Git Documentation](https://git-scm.com/doc)
- [GitHub CLI](https://cli.github.com)
- [Personal Access Tokens](https://github.com/settings/tokens)