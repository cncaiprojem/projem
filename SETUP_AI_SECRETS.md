# 🔐 GitHub Secrets Setup for AI Code Review

## Gerekli Secret'lar

### 1. **GEMINI_API_KEY** (Ücretsiz)
Google Gemini API key almak için:

1. https://makersuite.google.com/app/apikey adresine gidin
2. Google hesabınızla giriş yapın
3. "Create API Key" butonuna tıklayın
4. API key'i kopyalayın

### 2. **OPENAI_API_KEY** (Ücretli - Opsiyonel)
Copilot için OpenAI API key:

1. https://platform.openai.com/api-keys adresine gidin
2. "Create new secret key" tıklayın
3. Key'i kopyalayın

## GitHub'a Secret Ekleme

1. **Repository'ye gidin:**
   https://github.com/shaptina/projem

2. **Settings → Secrets and variables → Actions**

3. **"New repository secret" butonuna tıklayın**

4. **Secret'ları ekleyin:**

   | Name | Value |
   |------|-------|
   | `GEMINI_API_KEY` | Gemini API key'iniz |
   | `OPENAI_API_KEY` | OpenAI API key'iniz (opsiyonel) |

## Workflow Durumu

### ✅ Çalışacak Olanlar (API Key Olmadan):
- **CodeQL Security Analysis** - Otomatik çalışır
- **Basic Linting** - Otomatik çalışır
- **Summary Report** - Otomatik çalışır

### 🔑 API Key Gerektirenler:
- **Gemini Code Review** - GEMINI_API_KEY gerekli
- **GitHub Copilot** - OPENAI_API_KEY gerekli (veya GitHub Copilot subscription)

## Test Etmek İçin

1. Secret'ları ekledikten sonra:
   ```bash
   # Workflow'u manuel tetikle
   git commit --allow-empty -m "test: Trigger AI review"
   git push
   ```

2. GitHub Actions tab'ında kontrol edin:
   https://github.com/shaptina/projem/actions

## Minimal Setup (Sadece Ücretsiz)

Eğer sadece ücretsiz tool'ları kullanmak isterseniz:

1. Sadece `GEMINI_API_KEY` ekleyin (ücretsiz)
2. Copilot job'ı otomatik skip olacak
3. CodeQL ve Linting çalışmaya devam edecek

## Beklenen Sonuçlar

### PR'da Görecekleriniz:

1. **Gemini Review Comment:**
   - Security issues
   - Performance suggestions
   - Turkish localization fixes
   - Code quality improvements

2. **CodeQL Alerts:**
   - Security vulnerabilities
   - Code scanning results

3. **Linting Results:**
   - Style issues
   - Format problems

## Troubleshooting

### Gemini Review Çalışmıyor
- GEMINI_API_KEY doğru eklendi mi?
- API key aktif mi?
- Quota aşılmış olabilir mi?

### Copilot Review Çalışmıyor
- OPENAI_API_KEY eklendi mi?
- API credit var mı?
- GitHub Copilot subscription'ınız var mı?

### Workflow Fail Oluyor
- Actions tab'ında log'ları kontrol edin
- Secret'lar doğru isimle eklendi mi?
- Repository permissions doğru mu?

## Örnek PR Comment

```markdown
## 🤖 Gemini Code Review

### 🔒 Security Issues Found:
- Line 10: Hardcoded password detected: `PASSWORD = "admin123"`
- Line 14: SQL injection vulnerability in query construction

### ⚡ Performance Issues:
- Line 18-23: Nested loops causing O(n²) complexity

### 🇹🇷 Turkish Localization:
- Line 35: "Dunya" should be "Dünya"

### 📝 Code Quality:
- Missing type hints in function parameters
- Unused variable `z` on line 42

---
*Reviewed by Google Gemini AI*
```