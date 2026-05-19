import sys
import os

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from rag import index_kb_folder

if __name__ == "__main__":
    print("Starting KB indexing...")
    result = index_kb_folder()
    print(f"Indexing complete: {result}")
