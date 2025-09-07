#!/bin/bash
#
# Task 7.18: Container Security Hardening Script
# 
# This script hardens Docker containers for FreeCAD execution with:
# - Read-only filesystem setup
# - Capability dropping
# - Seccomp/AppArmor profiles
# - Network isolation
# - Resource limits

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
CONTAINER_NAME="${CONTAINER_NAME:-freecad-secure}"
FREECAD_VERSION="${FREECAD_VERSION:-1.1.0}"
OCCT_VERSION="${OCCT_VERSION:-7.8.1}"
SECURITY_LEVEL="${SECURITY_LEVEL:-production}"

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILES_DIR="${SCRIPT_DIR}/security-profiles"
SANDBOX_DIR="/tmp/freecad-sandbox"

# Logging
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create security profiles directory
create_security_profiles() {
    log_info "Creating security profiles directory..."
    mkdir -p "${PROFILES_DIR}"
    
    # Create seccomp profile
    cat > "${PROFILES_DIR}/freecad-seccomp.json" << 'EOF'
{
    "defaultAction": "SCMP_ACT_ERRNO",
    "architectures": [
        "SCMP_ARCH_X86_64",
        "SCMP_ARCH_X86",
        "SCMP_ARCH_X32"
    ],
    "syscalls": [
        {
            "names": [
                "accept",
                "accept4",
                "access",
                "arch_prctl",
                "bind",
                "brk",
                "chdir",
                "chmod",
                "chown",
                "clock_getres",
                "clock_gettime",
                "clock_nanosleep",
                "close",
                "connect",
                "copy_file_range",
                "creat",
                "dup",
                "dup2",
                "dup3",
                "epoll_create",
                "epoll_create1",
                "epoll_ctl",
                "epoll_ctl_old",
                "epoll_pwait",
                "epoll_wait",
                "epoll_wait_old",
                "eventfd",
                "eventfd2",
                "execve",
                "execveat",
                "exit",
                "exit_group",
                "faccessat",
                "fadvise64",
                "fallocate",
                "fanotify_mark",
                "fchdir",
                "fchmod",
                "fchmodat",
                "fchown",
                "fchownat",
                "fcntl",
                "fdatasync",
                "fgetxattr",
                "flistxattr",
                "flock",
                "fork",
                "fremovexattr",
                "fsetxattr",
                "fstat",
                "fstatat64",
                "fstatfs",
                "fsync",
                "ftruncate",
                "futex",
                "futimesat",
                "getcpu",
                "getcwd",
                "getdents",
                "getdents64",
                "getegid",
                "geteuid",
                "getgid",
                "getgroups",
                "getitimer",
                "getpeername",
                "getpgid",
                "getpgrp",
                "getpid",
                "getppid",
                "getpriority",
                "getrandom",
                "getresgid",
                "getresuid",
                "getrlimit",
                "getrusage",
                "getsid",
                "getsockname",
                "getsockopt",
                "gettid",
                "gettimeofday",
                "getuid",
                "getxattr",
                "inotify_add_watch",
                "inotify_init",
                "inotify_init1",
                "inotify_rm_watch",
                "io_cancel",
                "io_destroy",
                "io_getevents",
                "io_setup",
                "io_submit",
                "ioctl",
                "kill",
                "lgetxattr",
                "link",
                "linkat",
                "listen",
                "listxattr",
                "llistxattr",
                "lremovexattr",
                "lseek",
                "lsetxattr",
                "lstat",
                "madvise",
                "memfd_create",
                "mincore",
                "mkdir",
                "mkdirat",
                "mknod",
                "mknodat",
                "mlock",
                "mlock2",
                "mlockall",
                "mmap",
                "mprotect",
                "mremap",
                "msgctl",
                "msgget",
                "msgrcv",
                "msgsnd",
                "msync",
                "munlock",
                "munlockall",
                "munmap",
                "nanosleep",
                "newfstatat",
                "open",
                "openat",
                "pause",
                "pipe",
                "pipe2",
                "poll",
                "ppoll",
                "prctl",
                "pread64",
                "preadv",
                "preadv2",
                "prlimit64",
                "pselect6",
                "pwrite64",
                "pwritev",
                "pwritev2",
                "read",
                "readahead",
                "readlink",
                "readlinkat",
                "readv",
                "recv",
                "recvfrom",
                "recvmmsg",
                "recvmsg",
                "remap_file_pages",
                "removexattr",
                "rename",
                "renameat",
                "renameat2",
                "restart_syscall",
                "rmdir",
                "rt_sigaction",
                "rt_sigpending",
                "rt_sigprocmask",
                "rt_sigqueueinfo",
                "rt_sigreturn",
                "rt_sigsuspend",
                "rt_sigtimedwait",
                "rt_tgsigqueueinfo",
                "sched_getaffinity",
                "sched_getattr",
                "sched_getparam",
                "sched_get_priority_max",
                "sched_get_priority_min",
                "sched_getscheduler",
                "sched_rr_get_interval",
                "sched_setaffinity",
                "sched_setattr",
                "sched_setparam",
                "sched_setscheduler",
                "sched_yield",
                "seccomp",
                "select",
                "semctl",
                "semget",
                "semop",
                "semtimedop",
                "send",
                "sendfile",
                "sendmmsg",
                "sendmsg",
                "sendto",
                "setfsgid",
                "setfsuid",
                "setgid",
                "setgroups",
                "setitimer",
                "setpgid",
                "setpriority",
                "setregid",
                "setresgid",
                "setresuid",
                "setreuid",
                "setrlimit",
                "set_robust_list",
                "setsid",
                "setsockopt",
                "set_tid_address",
                "setuid",
                "setxattr",
                "shmat",
                "shmctl",
                "shmdt",
                "shmget",
                "shutdown",
                "sigaltstack",
                "signalfd",
                "signalfd4",
                "socket",
                "socketpair",
                "splice",
                "stat",
                "statfs",
                "statx",
                "symlink",
                "symlinkat",
                "sync",
                "sync_file_range",
                "syncfs",
                "sysinfo",
                "tee",
                "tgkill",
                "time",
                "timer_create",
                "timer_delete",
                "timer_getoverrun",
                "timer_gettime",
                "timer_settime",
                "times",
                "tkill",
                "truncate",
                "umask",
                "uname",
                "unlink",
                "unlinkat",
                "utime",
                "utimensat",
                "utimes",
                "vfork",
                "vmsplice",
                "wait4",
                "waitid",
                "waitpid",
                "write",
                "writev"
            ],
            "action": "SCMP_ACT_ALLOW"
        }
    ]
}
EOF

    # Create AppArmor profile
    cat > "${PROFILES_DIR}/freecad-apparmor" << EOF
#include <tunables/global>

profile docker-freecad flags=(attach_disconnected,mediate_deleted) {
  #include <abstractions/base>

  # Network access (deny for production)
  $(if [ "$SECURITY_LEVEL" = "production" ]; then echo "deny network,"; else echo "network inet tcp,"; fi)
  
  # Capability access (minimal)
  capability chown,
  capability dac_override,
  capability setuid,
  capability setgid,
  capability fowner,
  
  # Deny other capabilities
  deny capability sys_admin,
  deny capability sys_module,
  deny capability sys_rawio,
  deny capability sys_ptrace,
  deny capability sys_pacct,
  deny capability sys_nice,
  deny capability sys_resource,
  deny capability sys_time,
  deny capability sys_tty_config,
  deny capability syslog,
  deny capability audit_control,
  deny capability audit_write,
  deny capability audit_read,
  
  # File access rules
  /usr/bin/FreeCAD* ix,
  /usr/bin/FreeCADCmd ix,
  /usr/bin/python3* ix,
  
  # Libraries (read-only)
  /usr/lib/** r,
  /usr/local/lib/** r,
  /lib/** r,
  /lib64/** r,
  
  # FreeCAD specific
  /usr/share/freecad/** r,
  /usr/lib/freecad/** r,
  
  # Python packages (read-only)
  /usr/lib/python3*/** r,
  /usr/local/lib/python3*/** r,
  
  # Sandbox directory (read-write)
  ${SANDBOX_DIR}/** rw,
  
  # Temp directory
  /tmp/** rw,
  /var/tmp/** rw,
  
  # Process info
  /proc/sys/kernel/random/uuid r,
  /proc/self/** r,
  /proc/meminfo r,
  /proc/cpuinfo r,
  
  # Device access (minimal)
  /dev/null rw,
  /dev/zero rw,
  /dev/random r,
  /dev/urandom r,
  /dev/shm/** rw,
  
  # Deny access to sensitive areas
  deny /etc/shadow r,
  deny /etc/gshadow r,
  deny /etc/passwd w,
  deny /etc/group w,
  deny /root/** rwx,
  deny /home/** rwx,
  deny /boot/** rwx,
  deny /sys/** w,
  
  # Deny ptrace
  deny ptrace,
  
  # Deny mount operations
  deny mount,
  deny umount,
  deny pivot_root,
}
EOF

    log_info "Security profiles created"
}

# Create Dockerfile for hardened container
create_hardened_dockerfile() {
    log_info "Creating hardened Dockerfile..."
    
    cat > "${SCRIPT_DIR}/Dockerfile.secure" << EOF
FROM ubuntu:22.04 AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \\
    build-essential \\
    cmake \\
    git \\
    python3-dev \\
    python3-pip \\
    libfreecad-dev \\
    libocct-dev \\
    && rm -rf /var/lib/apt/lists/*

# Final stage - minimal runtime
FROM ubuntu:22.04

# Install only runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \\
    python3 \\
    python3-pip \\
    freecad-common=${FREECAD_VERSION}* \\
    libocct-foundation-${OCCT_VERSION} \\
    libocct-modeling-algorithms-${OCCT_VERSION} \\
    libocct-modeling-data-${OCCT_VERSION} \\
    libocct-ocaf-${OCCT_VERSION} \\
    libocct-visualization-${OCCT_VERSION} \\
    && apt-get clean \\
    && rm -rf /var/lib/apt/lists/* \\
    && rm -rf /usr/share/doc/* \\
    && rm -rf /usr/share/man/*

# Create non-root user
RUN groupadd -r freecad && useradd -r -g freecad -u 1000 freecad

# Remove package managers and compilers
RUN apt-get remove -y --purge \\
    gcc \\
    g++ \\
    make \\
    cmake \\
    apt \\
    dpkg \\
    && rm -rf /usr/bin/apt* \\
    && rm -rf /usr/bin/dpkg*

# Create sandbox directory
RUN mkdir -p ${SANDBOX_DIR} \\
    && chown -R freecad:freecad ${SANDBOX_DIR} \\
    && chmod 700 ${SANDBOX_DIR}

# Copy FreeCAD binaries
COPY --from=builder /usr/bin/FreeCAD* /usr/bin/
COPY --from=builder /usr/lib/freecad /usr/lib/freecad
COPY --from=builder /usr/share/freecad /usr/share/freecad

# Set up Python restrictions
COPY restrict_python.py /usr/local/bin/
ENV PYTHONSTARTUP=/usr/local/bin/restrict_python.py

# Switch to non-root user
USER freecad
WORKDIR ${SANDBOX_DIR}

# Set security environment variables
ENV FREECAD_SECURITY_LEVEL=${SECURITY_LEVEL}
ENV FREECAD_DISABLE_MACROS=1
ENV FREECAD_DISABLE_ADDONS=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONNOUSERSITE=1

# Entry point
ENTRYPOINT ["/usr/bin/FreeCADCmd"]
EOF

    # Create Python restriction script using centralized configuration
    # This script is generated from apps/api/app/core/security_config.py
    # To update, use: python -m app.utils.module_restrictions_generator --sync-shell
    cat > "${SCRIPT_DIR}/restrict_python.py" << 'EOF'
#!/usr/bin/env python3
"""
Python startup script to restrict module imports and dangerous functions
Generated by ModuleRestrictionsGenerator for production environment
"""
import builtins
import sys

# Save original import
_original_import = builtins.__import__

# Define allowed modules (from centralized configuration)
ALLOWED_MODULES = ['FreeCAD', 'FreeCADGui', 'Part', 'Draft', 'Sketcher', 'abc', 'base64', 'collections', 'dataclasses', 'datetime', 'decimal', 'enum', 'fractions', 'functools', 'itertools', 'json', 'math', 'numbers', 'typing']

# Define blocked modules (from centralized configuration)  
BLOCKED_MODULES = ['__builtin__', '__builtins__', 'asyncio', 'cgi', 'cgitb', 'compile', 'ctypes', 'dbm', 'eval', 'exec', 'fcntl', 'ftplib', 'http', 'imaplib', 'importlib', 'input', 'marshal', 'mmap', 'multiprocessing', 'open', 'os', 'pickle', 'poplib', 'pty', 'raw_input', 'shelve', 'shlex', 'signal', 'smtplib', 'socket', 'sqlite3', 'subprocess', 'sys', 'telnetlib', 'threading', 'urllib', 'xmlrpc', '__import__']

def restricted_import(name, *args, **kwargs):
    """Restricted import function"""
    base_name = name.split('.')[0]
    
    if base_name in BLOCKED_MODULES:
        raise ImportError(f"Module '{base_name}' is blocked for security")
    
    if base_name not in ALLOWED_MODULES:
        raise ImportError(f"Module '{base_name}' is not allowed")
    
    return _original_import(name, *args, **kwargs)

# Replace import
builtins.__import__ = restricted_import

# Remove dangerous builtins (but NOT __import__ as it's already replaced)
# __import__ is needed for Python's import statement to work
for dangerous in ['eval', 'exec', 'compile']:
    if hasattr(builtins, dangerous):
        delattr(builtins, dangerous)

print("Python security restrictions applied")
EOF

    log_info "Hardened Dockerfile created"
}

# Build hardened container
build_hardened_container() {
    log_info "Building hardened container..."
    
    docker build \
        -f "${SCRIPT_DIR}/Dockerfile.secure" \
        -t "${CONTAINER_NAME}:${FREECAD_VERSION}" \
        --build-arg FREECAD_VERSION="${FREECAD_VERSION}" \
        --build-arg OCCT_VERSION="${OCCT_VERSION}" \
        --build-arg SECURITY_LEVEL="${SECURITY_LEVEL}" \
        "${SCRIPT_DIR}"
    
    log_info "Container built successfully"
}

# Run container with security options
run_secure_container() {
    log_info "Running container with security hardening..."
    
    # Prepare security options - build array dynamically
    SECURITY_OPTS=()
    
    # Read-only root filesystem
    SECURITY_OPTS+=("--read-only")
    
    # No new privileges
    SECURITY_OPTS+=("--security-opt=no-new-privileges:true")
    
    # Drop all capabilities
    SECURITY_OPTS+=("--cap-drop=ALL")
    
    # Add only required capabilities
    SECURITY_OPTS+=("--cap-add=CHOWN")
    SECURITY_OPTS+=("--cap-add=SETUID")
    SECURITY_OPTS+=("--cap-add=SETGID")
    
    # Seccomp profile
    SECURITY_OPTS+=("--security-opt=seccomp=${PROFILES_DIR}/freecad-seccomp.json")
    
    # AppArmor profile (if available)
    if [ -f /sys/kernel/security/apparmor/profiles ]; then 
        SECURITY_OPTS+=("--security-opt=apparmor=docker-freecad")
    fi
    
    # PID namespace isolation
    SECURITY_OPTS+=("--pid=private")
    
    # Network isolation (no network in production)
    if [ "$SECURITY_LEVEL" = "production" ]; then 
        SECURITY_OPTS+=("--network=none")
    else
        SECURITY_OPTS+=("--network=bridge")
    fi
    
    # Resource limits
    SECURITY_OPTS+=("--memory=2g")
    SECURITY_OPTS+=("--memory-swap=2g")
    SECURITY_OPTS+=("--cpus=2")
    SECURITY_OPTS+=("--pids-limit=100")
    
    # Filesystem limits
    SECURITY_OPTS+=("--ulimit" "nofile=256:512")
    SECURITY_OPTS+=("--ulimit" "nproc=100:200")
    
    # Tmpfs for writable areas
    SECURITY_OPTS+=("--tmpfs" "/tmp:rw,noexec,nosuid,size=100m")
    SECURITY_OPTS+=("--tmpfs" "/var/tmp:rw,noexec,nosuid,size=100m")
    SECURITY_OPTS+=("--tmpfs" "${SANDBOX_DIR}:rw,noexec,nosuid,size=500m")
    
    # User namespace remapping
    # Note: --userns=host disables user namespace isolation
    # For better security, we should use proper user namespace remapping
    # Comment out for now as it reduces security isolation
    # SECURITY_OPTS+=("--userns=host")
    
    # Use proper user namespace remapping instead (if available)
    # This provides better isolation than --userns=host
    if docker info 2>/dev/null | grep -q "userns"; then
        log_info "Using user namespace remapping for better isolation"
        # Let Docker use its configured user namespace remapping
        # Do not specify --userns flag to use default remapping
    else
        log_warn "User namespace remapping not available - running with reduced isolation"
    fi
    
    # Remove environment variables
    SECURITY_OPTS+=("--env-file=/dev/null")
    
    # Specific environment variables
    SECURITY_OPTS+=("--env" "FREECAD_SECURITY_LEVEL=${SECURITY_LEVEL}")
    SECURITY_OPTS+=("--env" "FREECAD_DISABLE_MACROS=1")
    SECURITY_OPTS+=("--env" "FREECAD_DISABLE_ADDONS=1")
    
    # Run container
    docker run \
        "${SECURITY_OPTS[@]}" \
        --rm \
        --name "${CONTAINER_NAME}-instance" \
        "${CONTAINER_NAME}:${FREECAD_VERSION}" \
        "$@"
}

# Verify security hardening
verify_hardening() {
    log_info "Verifying container hardening..."
    
    # Test container security
    docker run --rm "${CONTAINER_NAME}:${FREECAD_VERSION}" /bin/sh -c '
        echo "Testing security restrictions..."
        
        # Test read-only filesystem
        if touch /test 2>/dev/null; then
            echo "ERROR: Root filesystem is writable"
            exit 1
        fi
        
        # Test user privileges
        if [ "$(id -u)" = "0" ]; then
            echo "ERROR: Running as root"
            exit 1
        fi
        
        # Test Python restrictions
        python3 -c "
try:
    import os
    print(\"ERROR: os module accessible\")
    exit(1)
except ImportError:
    print(\"OK: os module blocked\")
        "
        
        echo "Security verification passed"
    '
    
    log_info "Hardening verification complete"
}

# Load AppArmor profile
load_apparmor_profile() {
    if [ -f /sys/kernel/security/apparmor/profiles ]; then
        log_info "Loading AppArmor profile..."
        
        if command -v apparmor_parser &> /dev/null; then
            sudo apparmor_parser -r "${PROFILES_DIR}/freecad-apparmor"
            log_info "AppArmor profile loaded"
        else
            log_warn "apparmor_parser not found, skipping AppArmor profile"
        fi
    else
        log_warn "AppArmor not available on this system"
    fi
}

# Main execution
main() {
    log_info "Starting container hardening for FreeCAD ${FREECAD_VERSION}"
    log_info "Security level: ${SECURITY_LEVEL}"
    
    # Create security profiles
    create_security_profiles
    
    # Load AppArmor if available
    load_apparmor_profile
    
    # Create and build container
    create_hardened_dockerfile
    build_hardened_container
    
    # Verify hardening
    verify_hardening
    
    log_info "Container hardening complete"
    log_info "To run the secure container, use:"
    log_info "  $0 run [FreeCAD arguments]"
}

# Handle command line arguments
case "${1:-}" in
    run)
        shift
        run_secure_container "$@"
        ;;
    verify)
        verify_hardening
        ;;
    build)
        main
        ;;
    *)
        echo "Usage: $0 {build|run|verify}"
        echo "  build  - Build hardened container"
        echo "  run    - Run container with security options"
        echo "  verify - Verify security hardening"
        exit 1
        ;;
esac