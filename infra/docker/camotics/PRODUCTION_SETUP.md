# CAMotics Production Setup

The current CAMotics Dockerfile includes a mock installation for demonstration purposes. For production deployment, follow these steps:

## Production Installation

1. **Download CAMotics Package**
   ```bash
   wget https://github.com/CauldronDevelopmentLLC/CAMotics/releases/download/v1.2.2/camotics_1.2.2_amd64.deb
   ```

2. **Verify Package Integrity** (if checksum available)
   ```bash
   sha256sum camotics_1.2.2_amd64.deb
   # Compare with published checksum
   ```

3. **Replace Mock Installation in Dockerfile**
   Replace the mock installation section with:
   ```dockerfile
   # Download and install CAMotics from official releases
   RUN cd /tmp \
       && wget -O camotics.deb \
          "https://github.com/CauldronDevelopmentLLC/CAMotics/releases/download/v${CAMOTICS_VERSION}/camotics_${CAMOTICS_VERSION}_amd64.deb" \
       && dpkg -i camotics.deb || apt-get install -f -y \
       && rm -f camotics.deb
   ```

4. **Build Production Image**
   ```bash
   docker build -t camotics-utility:1.2-prod .
   ```

## Verification

Test the production installation:
```bash
docker run --rm camotics-utility:1.2-prod camotics --version
```

## Alternative: Use Upstream Image

Consider using the official CAMotics Docker image if available:
```bash
docker pull jrottenberg/camotics:1.2
```

## Security Considerations

- Always verify package checksums
- Use specific version tags
- Scan images for vulnerabilities
- Keep base images updated