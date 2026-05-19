import json
import os
import glob

KB_DIR = r"d:\antigravity workspace\real-estate-leads\data\knowledge_base"
SCRAPED_DIR = os.path.join(KB_DIR, "scraped_leads")
OUTPUT_FILE = os.path.join(KB_DIR, "leads_qa.txt")

def consolidate_qa():
    qa_list = []
    
    # Load all JSON files in the scraped_leads directory
    json_files = glob.glob(os.path.join(SCRAPED_DIR, "*.json"))
    
    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
                # Check if it's a list of chats with 'qa' entries
                for chat in data:
                    if "qa" in chat:
                        for item in chat["qa"]:
                            qa_list.append(item)
                    elif "messages" in chat:
                        # Fallback for raw message format: try to find Q&A patterns
                        messages = chat["messages"]
                        for i in range(len(messages) - 1):
                            msg = messages[i]
                            next_msg = messages[i+1]
                            
                            if msg["role"] == "lead" and "?" in msg["text"] and next_msg["role"] == "me":
                                qa_list.append({
                                    "question": msg["text"],
                                    "answer": next_msg["text"]
                                })
        except Exception as e:
            print(f"Error processing {file_path}: {e}")

    # Write to text file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("# Leads Q&A Knowledge Base - Armstrong Properties\n\n")
        for qa in qa_list:
            f.write(f"Question: {qa['question'].strip()}\n")
            f.write(f"Answer: {qa['answer'].strip()}\n")
            f.write("-" * 20 + "\n")
            
    print(f"Consolidated {len(qa_list)} Q&A pairs to {OUTPUT_FILE}")

if __name__ == "__main__":
    consolidate_qa()
