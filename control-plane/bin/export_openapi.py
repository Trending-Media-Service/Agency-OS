import json
import sys
import os

# Add parent directory to path so app can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app

def main():
    print(json.dumps(app.openapi(), indent=2))

if __name__ == "__main__":
    main()
