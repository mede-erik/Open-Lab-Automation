#!/usr/bin/env python3
"""
Launcher script per Open Lab Automation
Imposta il PYTHONPATH per eseguire l'applicazione come un pacchetto.
"""

import subprocess
import sys
import os

def main():
    """Avvia l'applicazione usando l'interprete Python corrente."""
    
    # Percorso della root del progetto (la cartella sopra a 'frontend')
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    frontend_dir = os.path.join(project_root, "frontend")
    
    print("=== Open Lab Automation Launcher ===")
    print(f"Project Root: {project_root}")
    print("Running application as a package...")
    print()
    
    # Imposta il PYTHONPATH per includere la root del progetto
    env = os.environ.copy()
    env['PYTHONPATH'] = project_root + os.pathsep + env.get('PYTHONPATH', '')
    
    # Comando per eseguire l'app come modulo
    # Usiamo sys.executable per garantire che venga usato lo stesso Python
    cmd = [sys.executable, "-m", "frontend.main"]
    
    print(f"Executing: {' '.join(cmd)}")
    print("=" * 50)
    
    try:
        # Esegue il comando con l'ambiente modificato
        # Non cambiamo la directory di lavoro, così i percorsi relativi
        # (se presenti) partono dalla root del progetto.
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