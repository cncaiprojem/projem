# GitHub Repository Oluşturma

## 📝 Manual Adımlar:

1. **GitHub.com'a gidin**
   - https://github.com/new

2. **Repository bilgileri:**
   - Repository name: `projem`
   - Description: `FreeCAD-based CNC/CAM/CAD production platform with Turkish UI/UX`
   - Public repository
   - DON'T initialize with README (zaten var)
   - DON'T add .gitignore (zaten var)
   - DON'T add license (sonra ekleyebilirsiniz)

3. **Create repository** butonuna tıklayın

## 🚀 Repository oluşturduktan sonra:

Push komutunu çalıştırın:

```bash
# Branch'i main olarak değiştir
git branch -M main

# Push to GitHub
git push -u origin main
```

## 📋 Alternatif: GitHub CLI ile

Eğer GitHub CLI yüklüyse:

```bash
# Login to GitHub
gh auth login

# Create repository
gh repo create projem --public --description "FreeCAD-based CNC/CAM/CAD production platform with Turkish UI/UX" --source=. --remote=origin --push
```

## 🔐 Authentication

Eğer push sırasında authentication hatası alırsanız:

1. **Personal Access Token kullanın:**
   - GitHub Settings > Developer settings > Personal access tokens
   - Generate new token (classic)
   - Scope: repo (full control)
   - Token'ı kopyalayın

2. **Push with token:**
```bash
git push https://your-token@github.com/kafge/projem.git main
```

## 📁 Repository Structure

```
projem/
├── apps/
│   ├── api/          # FastAPI backend
│   └── web/          # Next.js frontend
├── docker-compose.yml
├── Makefile
├── CLAUDE.md         # Claude Code documentation
├── README.md
└── .gitignore
```

## 🎯 Repository Features

- ✅ Monorepo architecture
- ✅ FastAPI + Next.js stack
- ✅ FreeCAD CAD/CAM integration
- ✅ Turkish UI/UX
- ✅ Docker Compose setup
- ✅ Production-ready configuration
- ✅ Comprehensive testing
- ✅ Claude Code agents
- ✅ MCP server configuration