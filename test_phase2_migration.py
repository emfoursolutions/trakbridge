#!/usr/bin/env python3
"""
Quick test script to verify Phase 2 migration is working
"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    # Test the import and basic functionality
    from services.cot_service import get_cot_service
    from services.cot_service_integration import QueuedCOTService
    
    print("✅ Successfully imported get_cot_service and QueuedCOTService")
    
    # Test that get_cot_service returns QueuedCOTService type
    service = get_cot_service()
    print(f"✅ get_cot_service() returned: {type(service).__name__}")
    
    if isinstance(service, QueuedCOTService):
        print("✅ Service is correctly using QueuedCOTService")
    else:
        print(f"❌ Expected QueuedCOTService, got {type(service).__name__}")
        sys.exit(1)
        
    # Test basic methods exist
    required_methods = ['enqueue_event', 'enqueue_with_replacement', 'start_worker', 'stop_worker']
    for method in required_methods:
        if hasattr(service, method):
            print(f"✅ Method {method} exists")
        else:
            print(f"❌ Method {method} missing")
            sys.exit(1)
    
    print("\n🎉 Phase 2 migration successful! All backward compatibility checks passed.")
    
except Exception as e:
    print(f"❌ Migration test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)