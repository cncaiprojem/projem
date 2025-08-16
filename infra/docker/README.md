# Utility Docker Images

This directory contains enterprise-grade utility Docker images for the FreeCAD CAM/CAD platform. Each utility is containerized with security hardening and follows production best practices.

## Available Utilities

### 🔧 FreeCAD Utility (`freecad/`)
- **Purpose**: CAD/CAM processing and FreeCAD script execution
- **Version**: FreeCAD 1.1.x
- **User**: Non-root (UID 10001)
- **Features**: Headless operation, security hardening, health checks

### 🎯 CAMotics Utility (`camotics/`)
- **Purpose**: G-code simulation and CAM verification
- **Version**: CAMotics 1.2.x
- **User**: Non-root (UID 10002)
- **Features**: Virtual display, headless simulation, batch processing

### 🎬 FFmpeg Utility (`ffmpeg/`)
- **Purpose**: Video/audio processing for simulation recordings
- **Version**: FFmpeg 6.1.x
- **User**: Non-root (UID 10003)
- **Features**: Alpine-based, minimal footprint, comprehensive codec support

### 🛡️ ClamAV Utility (`clamav/`)
- **Purpose**: Antivirus scanning for uploaded and generated files
- **Version**: ClamAV 1.3.x
- **User**: Non-root (UID 10004)
- **Features**: Auto-updating database, comprehensive scanning, daemon mode

## Security Features

All utility images implement enterprise-grade security:

- ✅ **Non-root execution** with fixed UIDs
- ✅ **Pinned base image versions** (SHA256 digests)
- ✅ **Minimal attack surface** (only essential packages)
- ✅ **Read-only filesystem** compatibility
- ✅ **No-new-privileges** security option
- ✅ **Health checks** for container integrity
- ✅ **dumb-init** for proper signal handling
- ✅ **Comprehensive logging** configuration

## Quick Start

### Build All Images
```bash
cd infra/docker
docker-compose -f docker-compose.utilities.yml build
```

### Start All Services
```bash
docker-compose -f docker-compose.utilities.yml up -d
```

### Test Individual Services
```bash
# FreeCAD version check
docker-compose -f docker-compose.utilities.yml exec freecad-utility freecadcmd --version

# CAMotics version check
docker-compose -f docker-compose.utilities.yml exec camotics-utility camotics --version

# FFmpeg version check
docker-compose -f docker-compose.utilities.yml exec ffmpeg-utility ffmpeg -version

# ClamAV version check
docker-compose -f docker-compose.utilities.yml exec clamav-utility clamscan --version
```

## Usage Examples

### FreeCAD Processing
```bash
# Run FreeCAD script
docker run --rm -v /path/to/scripts:/workspace freecad-utility:1.1 script.py

# Interactive Python session
docker run --rm -it freecad-utility:1.1 -c "import FreeCAD; print(FreeCAD.Version())"
```

### CAMotics Simulation
```bash
# Simulate G-code
docker run --rm -v /data:/workspace camotics-utility:1.2 --simulate program.gcode

# Export simulation as STL
docker run --rm -v /data:/workspace camotics-utility:1.2 \
  --export-simulation output.stl input.gcode
```

### FFmpeg Video Processing
```bash
# Convert video format
docker run --rm -v /videos:/workspace ffmpeg-utility:6.1 \
  -i input.avi -c:v libx264 -c:a aac output.mp4

# Create time-lapse
docker run --rm -v /data:/workspace ffmpeg-utility:6.1 \
  -framerate 30 -i frame_%04d.png -c:v libx264 -r 30 timelapse.mp4
```

### ClamAV Virus Scanning
```bash
# Scan directory
docker run --rm -v /uploads:/workspace clamav-utility:1.3 \
  --recursive --verbose /workspace

# Scan single file
docker run --rm -v /data:/workspace clamav-utility:1.3 \
  /workspace/suspicious-file.exe
```

## Integration with Main Platform

These utilities are designed to be accessed by the main platform's worker services:

1. **FreeCAD workers** can use `freecad-utility` for CAD processing
2. **Simulation workers** can use `camotics-utility` for G-code verification
3. **Video workers** can use `ffmpeg-utility` for rendering simulation videos
4. **Security workers** can use `clamav-utility` for file scanning

### Worker Integration Example
```python
# In Celery worker
import subprocess

def process_cad_file(file_path):
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{file_path}:/workspace/input.fcstd",
        "freecad-utility:1.1",
        "-c", "import FreeCAD; doc = FreeCAD.open('/workspace/input.fcstd'); ..."
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout
```

## Directory Structure

```
infra/docker/
├── freecad/
│   └── Dockerfile              # FreeCAD utility image
├── camotics/
│   └── Dockerfile              # CAMotics utility image
├── ffmpeg/
│   └── Dockerfile              # FFmpeg utility image
├── clamav/
│   └── Dockerfile              # ClamAV utility image
├── workspace/                  # Runtime workspaces
│   ├── freecad/               # FreeCAD workspace
│   ├── camotics/              # CAMotics workspace
│   ├── ffmpeg/                # FFmpeg workspace
│   └── clamav/                # ClamAV workspace
├── data/
│   └── clamav/                # ClamAV database persistence
├── docker-compose.utilities.yml  # Orchestration file
└── README.md                   # This file
```

## Resource Requirements

| Service | CPU | Memory | Storage |
|---------|-----|--------|---------|
| FreeCAD | 0.5-2.0 cores | 1-4GB | 100MB temp |
| CAMotics | 0.5-2.0 cores | 2-6GB | 200MB temp |
| FFmpeg | 1.0-4.0 cores | 2-8GB | 500MB temp |
| ClamAV | 0.2-1.0 cores | 512MB-2GB | 100MB + database |

## Monitoring & Health Checks

All services include comprehensive health checks:

- **FreeCAD**: `freecadcmd --version` every 30s
- **CAMotics**: `camotics --version` every 30s  
- **FFmpeg**: `ffmpeg -version` every 30s
- **ClamAV**: `clamscan --version` every 60s

Health status can be monitored via:
```bash
docker-compose -f docker-compose.utilities.yml ps
```

## Security Considerations

### Container Security
- All containers run as non-root users
- Read-only filesystem where possible
- No unnecessary capabilities
- Tmpfs mounts for temporary files
- Network isolation

### Image Security
- Base images pinned with SHA256 digests
- Package versions explicitly specified
- Regular security updates
- Minimal package installation
- No development tools in production images

### Runtime Security
- Resource limits enforced
- Security options configured
- Logging centralized
- Health monitoring enabled

## Troubleshooting

### Common Issues

**FreeCAD Import Errors**
```bash
# Check FreeCAD installation
docker run --rm freecad-utility:1.1 freecadcmd -c "import FreeCAD; print('OK')"
```

**CAMotics Display Issues**
```bash
# Verify virtual display is working
docker run --rm camotics-utility:1.2 sh -c "export DISPLAY=:99; Xvfb :99 & sleep 2; camotics --version"
```

**FFmpeg Codec Issues**
```bash
# List available codecs
docker run --rm ffmpeg-utility:6.1 ffmpeg -codecs
```

**ClamAV Database Issues**
```bash
# Update virus database
docker run --rm -v clamav_db:/var/lib/clamav clamav-utility:1.3 freshclam --no-warnings
```

### Log Analysis
```bash
# View service logs
docker-compose -f docker-compose.utilities.yml logs -f [service-name]

# Check health status
docker inspect --format='{{.State.Health.Status}}' util_freecad
```

## Development & Customization

### Building Custom Images
```bash
# Build with custom args
docker build --build-arg FREECAD_VERSION=1.1.0 -t freecad-utility:custom ./freecad/
```

### Adding New Utilities
1. Create new directory under `infra/docker/`
2. Add Dockerfile with security hardening
3. Update `docker-compose.utilities.yml`
4. Add workspace directory
5. Update this README

### Testing Changes
```bash
# Test individual image
docker build -t test-utility ./new-utility/
docker run --rm test-utility --version

# Test compose integration
docker-compose -f docker-compose.utilities.yml up new-utility
```

## Production Deployment

For production deployment, consider:

1. **Registry**: Push images to private container registry
2. **Kubernetes**: Use Helm charts for orchestration
3. **Monitoring**: Integrate with Prometheus/Grafana
4. **Logging**: Configure centralized logging
5. **Secrets**: Use proper secret management
6. **Updates**: Automate security updates
7. **Scaling**: Configure auto-scaling based on load

## License

These utility containers are part of the FreeCAD CAM/CAD platform and follow the same licensing terms.