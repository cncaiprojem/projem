#!/usr/bin/env python3
"""
Demonstration of PR #473 batch delete fix.
Shows how the error handling now correctly returns partial success counts.
"""


class MockError:
    """Mock error object for demonstration."""
    def __init__(self, name, message):
        self.object_name = name
        self.error_message = message


def old_buggy_logic(errors, batch_size):
    """The OLD buggy implementation that returns 0 on any error."""
    error_count = 0
    for error in errors:
        error_count += 1
        print(f"  Error: {error.object_name} - {error.error_message}")
    
    # OLD LOGIC: Returns 0 if ANY error occurred
    return batch_size if error_count == 0 else 0


def new_fixed_logic(errors, batch_size):
    """The NEW fixed implementation that returns actual successful count."""
    error_count = 0
    for error in errors:
        error_count += 1
        print(f"  Error: {error.object_name} - {error.error_message}")
    
    # NEW LOGIC: Returns actual number of successful deletions
    successful_deletions = batch_size - error_count
    
    if error_count > 0:
        print(f"  Info: Batch delete completed with {error_count} errors, {successful_deletions} successful")
    
    return successful_deletions


def demonstrate_scenario(scenario_name, errors, batch_size):
    """Demonstrate a specific scenario with both old and new logic."""
    print(f"\n{scenario_name}")
    print("-" * 60)
    print(f"Batch size: {batch_size} objects")
    print(f"Errors: {len(list(errors))} objects failed")
    
    # Reset errors iterator for each test
    errors_for_old = list(errors)
    errors_for_new = list(errors)
    
    print("\nOLD BUGGY LOGIC:")
    old_result = old_buggy_logic(errors_for_old, batch_size)
    print(f"  Returns: {old_result} (incorrectly returns 0 on any error)")
    
    print("\nNEW FIXED LOGIC:")
    new_result = new_fixed_logic(errors_for_new, batch_size)
    print(f"  Returns: {new_result} (correctly returns actual successful count)")
    
    print(f"\nDifference: Old returned {old_result}, New returns {new_result}")
    if old_result != new_result:
        print(f"  FIX IMPACT: Now correctly reports {new_result} successful deletions!")


def main():
    """Run demonstrations of various scenarios."""
    print("=" * 70)
    print("PR #473 BATCH DELETE FIX DEMONSTRATION")
    print("=" * 70)
    
    # Scenario 1: No errors
    demonstrate_scenario(
        "Scenario 1: Perfect Success (No Errors)",
        errors=[],
        batch_size=1000
    )
    
    # Scenario 2: Single error
    demonstrate_scenario(
        "Scenario 2: Single Error out of 1000",
        errors=[MockError("file-999.txt", "Access denied")],
        batch_size=1000
    )
    
    # Scenario 3: Multiple errors but mostly successful
    demonstrate_scenario(
        "Scenario 3: 5 Errors out of 1000 (99.5% success rate)",
        errors=[
            MockError("file-100.txt", "Not found"),
            MockError("file-200.txt", "Permission denied"),
            MockError("file-300.txt", "Locked by another process"),
            MockError("file-400.txt", "Network timeout"),
            MockError("file-500.txt", "Invalid key"),
        ],
        batch_size=1000
    )
    
    # Scenario 4: Half failed
    demonstrate_scenario(
        "Scenario 4: 50% Failure Rate",
        errors=[MockError(f"file-{i}.txt", "Error") for i in range(50)],
        batch_size=100
    )
    
    # Scenario 5: All failed
    demonstrate_scenario(
        "Scenario 5: Complete Failure (All Errors)",
        errors=[MockError(f"file-{i}.txt", "Error") for i in range(100)],
        batch_size=100
    )
    
    print("\n" + "=" * 70)
    print("SUMMARY: The fix ensures accurate reporting of successful deletions,")
    print("matching boto3 behavior and providing better visibility into partial failures.")
    print("=" * 70)


if __name__ == "__main__":
    main()