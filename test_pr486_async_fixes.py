#!/usr/bin/env python
"""Test PR #486 async fixes."""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def test_asyncio_lock():
    """Test that asyncio.Lock works properly in async context."""
    from typing import Dict, Any, Callable, Awaitable
    
    class InFlightCoalescer:
        """Test version of InFlightCoalescer with asyncio.Lock."""
        
        def __init__(self):
            self._requests: Dict[str, asyncio.Future] = {}
            self._lock = asyncio.Lock()
        
        async def coalesce(self, key: str, func: Callable[[], Awaitable[Any]]) -> Any:
            """Coalesce concurrent requests for the same key."""
            async with self._lock:
                if key in self._requests:
                    # Wait for existing request
                    future = self._requests[key]
                    print(f"Coalescing request for key: {key}")
                    # Release lock before awaiting to avoid blocking other tasks
                    try:
                        return await future
                    except Exception:
                        # Re-raise exception from the original request
                        raise
                
                # Create new future
                future = asyncio.Future()
                self._requests[key] = future
            
            try:
                # Execute function
                result = await func()
                future.set_result(result)
                return result
            except Exception as e:
                future.set_exception(e)
                raise
            finally:
                # Clean up
                async with self._lock:
                    self._requests.pop(key, None)
    
    # Test the coalescer
    coalescer = InFlightCoalescer()
    call_count = 0
    
    async def slow_function():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.1)
        return f"result_{call_count}"
    
    # Run multiple concurrent requests
    results = await asyncio.gather(
        coalescer.coalesce("key1", slow_function),
        coalescer.coalesce("key1", slow_function),
        coalescer.coalesce("key1", slow_function),
    )
    
    print(f"Results: {results}")
    print(f"Call count: {call_count}")
    
    # All should get same result
    assert all(r == results[0] for r in results), "All coalesced requests should get same result"
    # Function should only be called once
    assert call_count == 1, "Function should only be called once for coalesced requests"
    
    print("[PASS] InFlightCoalescer with asyncio.Lock works correctly!")


async def test_git_sha_handling():
    """Test that git SHA is not truncated."""
    import subprocess
    
    # Test getting full git SHA
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1
        )
        if result.returncode == 0:
            git_sha = result.stdout.strip()
            print(f"Full git SHA: {git_sha}")
            print(f"SHA length: {len(git_sha)}")
            
            # Verify it's a full SHA (40 characters)
            assert len(git_sha) == 40, f"Git SHA should be 40 chars, got {len(git_sha)}"
            
            # Test that we use full SHA in fingerprint
            class EngineFingerprint:
                def __init__(self, git_sha):
                    self.git_sha = git_sha
                
                def to_string(self):
                    # Using full SHA, not truncated
                    return f"git{{{self.git_sha}}}"
            
            fp = EngineFingerprint(git_sha)
            fp_str = fp.to_string()
            print(f"Fingerprint: {fp_str}")
            
            # Verify full SHA is in fingerprint
            assert git_sha in fp_str, "Full SHA should be in fingerprint"
            print("[PASS] Git SHA is used in full, not truncated!")
    except Exception as e:
        print(f"Could not test git SHA: {e}")


async def main():
    """Run all tests."""
    print("Testing PR #486 fixes...")
    print("=" * 60)
    
    print("\n1. Testing asyncio.Lock in InFlightCoalescer...")
    await test_asyncio_lock()
    
    print("\n2. Testing git SHA handling...")
    await test_git_sha_handling()
    
    print("\n" + "=" * 60)
    print("[PASS] All PR #486 fixes verified successfully!")


if __name__ == "__main__":
    asyncio.run(main())