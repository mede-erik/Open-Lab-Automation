#!/usr/bin/env python3
"""
Launcher script for Open Lab Automation
Sets up PYTHONPATH to run the application as a package.
"""

import subprocess
import sys
import os

def main():
    """Starts the application using the current Python interpreter."""
    
    # Project root path (the folder above 'frontend')
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    frontend_dir = os.path.join(project_root, "frontend")
    
    print("=== Open Lab Automation Launcher ===")
    print(f"Project Root: {project_root}")
    print("Running application as a package...")
    print()
    
    # Set PYTHONPATH to include project root
    env = os.environ.copy()
    env['PYTHONPATH'] = project_root + os.pathsep + env.get('PYTHONPATH', '')
    
    # Command to run the app as a module
    # We use sys.executable to ensure the same Python is used
    cmd = [sys.executable, "-m", "frontend.main"]
    
    print(f"Executing: {' '.join(cmd)}")
    print("=" * 50)
    
    try:
        # Execute the command with modified environment
        # We don't change the working directory, so relative paths
        # (if present) start from the project root.
        result = subprocess.run(cmd, env=env, check=False)
        sys.exit(result.returncode)
        
    except KeyboardInterrupt:
        print("\nApplication interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"ERROR during launch: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()