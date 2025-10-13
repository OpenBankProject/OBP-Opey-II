#!/usr/bin/env python3
"""
Quick test script to verify approval system integration.
Run this before starting the full service to check component initialization.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_imports():
    """Test that all approval system modules can be imported"""
    print("✓ Testing imports...")
    try:
        from agent.components.tools.approval_models import (
            RiskLevel, ApprovalLevel, ApprovalPattern, ApprovalAction,
            ToolApprovalMetadata, ApprovalContext, ApprovalDecision
        )
        print("  ✓ approval_models imported successfully")
        
        from agent.components.tools.tool_registry import ToolRegistry
        print("  ✓ tool_registry imported successfully")
        
        from agent.components.tools.approval_manager import ApprovalManager
        print("  ✓ approval_manager imported successfully")
        
        from agent.components.tools import get_tool_registry, create_approval_manager
        print("  ✓ __init__ exports imported successfully")
        
        return True
    except Exception as e:
        print(f"  ✗ Import failed: {e}")
        return False


def test_singleton_pattern():
    """Test that ToolRegistry is a singleton"""
    print("\n✓ Testing singleton pattern...")
    try:
        from agent.components.tools import get_tool_registry
        
        registry1 = get_tool_registry()
        registry2 = get_tool_registry()
        
        if registry1 is registry2:
            print("  ✓ ToolRegistry is a singleton (same instance)")
        else:
            print("  ✗ ToolRegistry is NOT a singleton (different instances)")
            return False
        
        return True
    except Exception as e:
        print(f"  ✗ Singleton test failed: {e}")
        return False


def test_tool_registration():
    """Test tool registration with approval metadata"""
    print("\n✓ Testing tool registration...")
    try:
        from agent.components.tools import get_tool_registry
        from agent.components.tools.approval_models import (
            ToolApprovalMetadata, ApprovalPattern, ApprovalAction,
            RiskLevel, ApprovalLevel
        )
        from langchain_core.tools import tool
        
        # Create a test tool
        @tool
        def test_tool(arg: str) -> str:
            """A test tool"""
            return f"Result: {arg}"
        
        registry = get_tool_registry()
        
        # Register with metadata
        registry.register_tool(
            tool=test_tool,
            approval_metadata=ToolApprovalMetadata(
                tool_name="test_tool",
                description="Test tool",
                requires_auth=False,
                default_risk_level=RiskLevel.SAFE,
                patterns=[
                    ApprovalPattern(
                        method="*",
                        path="*",
                        action=ApprovalAction.AUTO_APPROVE,
                        reason="Test tool"
                    )
                ],
                can_be_pre_approved=True,
                available_approval_levels=[ApprovalLevel.ONCE]
            )
        )
        
        print("  ✓ Tool registered successfully")
        
        # Check if tool is in registry
        registered_tool = registry.get_tool("test_tool")
        if registered_tool:
            print(f"  ✓ Tool found in registry: {registered_tool.tool.name}")
        else:
            print("  ✗ Tool NOT found in registry")
            return False
        
        # Check approval metadata
        metadata = registry.get_tool_metadata("test_tool")
        if metadata:
            print(f"  ✓ Approval metadata retrieved: risk={metadata.default_risk_level}")
        else:
            print("  ✗ Approval metadata NOT found")
            return False
        
        return True
    except Exception as e:
        print(f"  ✗ Tool registration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pattern_matching():
    """Test approval pattern matching"""
    print("\n✓ Testing pattern matching...")
    try:
        from agent.components.tools import get_tool_registry
        
        registry = get_tool_registry()
        
        # Test auto-approve pattern (from test_tool registered above)
        should_approve = registry.should_require_approval("test_tool", {"method": "GET"})
        
        if not should_approve:  # Should NOT require approval (auto-approved)
            print("  ✓ Pattern matching works (auto-approve detected)")
        else:
            print("  ✗ Pattern matching failed (should be auto-approved)")
            return False
        
        return True
    except Exception as e:
        print(f"  ✗ Pattern matching failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_approval_manager_creation():
    """Test ApprovalManager creation"""
    print("\n✓ Testing ApprovalManager creation...")
    try:
        from agent.components.tools import create_approval_manager
        
        # Create without Redis
        manager1 = create_approval_manager(redis_client=None, workspace_config={})
        print("  ✓ ApprovalManager created (no Redis)")
        
        # Create another instance (should be different)
        manager2 = create_approval_manager(redis_client=None, workspace_config={})
        
        if manager1 is not manager2:
            print("  ✓ ApprovalManager is NOT a singleton (per-session pattern)")
        else:
            print("  ✗ ApprovalManager should NOT be a singleton")
            return False
        
        return True
    except Exception as e:
        print(f"  ✗ ApprovalManager creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_approval_context_building():
    """Test building approval context"""
    print("\n✓ Testing approval context building...")
    try:
        from agent.components.tools import get_tool_registry
        
        registry = get_tool_registry()
        
        # Build approval context for test_tool
        context = registry.build_approval_context(
            tool_name="test_tool",
            tool_call_id="test_call_123",
            tool_args={"arg": "test_value"},
            session_history={"similar_count": 0}
        )
        
        print(f"  ✓ Approval context built:")
        print(f"    - Tool: {context.tool_name}")
        print(f"    - Call ID: {context.tool_call_id}")
        print(f"    - Risk Level: {context.risk_level}")
        print(f"    - Message: {context.message}")
        
        return True
    except Exception as e:
        print(f"  ✗ Context building failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("=" * 60)
    print("APPROVAL SYSTEM INTEGRATION TEST")
    print("=" * 60)
    
    tests = [
        ("Imports", test_imports),
        ("Singleton Pattern", test_singleton_pattern),
        ("Tool Registration", test_tool_registration),
        ("Pattern Matching", test_pattern_matching),
        ("ApprovalManager Creation", test_approval_manager_creation),
        ("Approval Context Building", test_approval_context_building),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ {name} failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    print("\n" + "=" * 60)
    print(f"SUMMARY: {passed}/{total} tests passed")
    print("=" * 60)
    
    if passed == total:
        print("\n🎉 All tests passed! Ready to start service.")
        return 0
    else:
        print("\n⚠️  Some tests failed. Check errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
