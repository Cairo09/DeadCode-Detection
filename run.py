"""Entry point for the Dead Code Detection tool."""
import os
import sys

if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(__file__))
    from backend.app import app
    print("=" * 60)
    print("  Dead Code & Unreachable Path Detection Tool")
    print("  http://localhost:5050")
    print("=" * 60)
    app.run(debug=True, port=5050)
