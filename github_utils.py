import base64
from github import Github
from datetime import datetime

def push_csv_to_github(csv_content, strategy_name, pat_token, repo_name, branch="main"):
    """
    Pushes generated report CSV directly to GitHub repository with strategy name and timestamp.
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_strat_name = strategy_name.lower().replace(" ", "_")
        filename = f"reports/{clean_strat_name}_{timestamp}.csv"
        
        g = Github(pat_token)
        repo = g.get_repo(repo_name)
        
        commit_message = f"Add automated backtest output: {filename}"
        
        print(f"[DEBUG] Uploading {filename} to GitHub repo {repo_name}...")
        
        repo.create_file(
            path=filename,
            message=commit_message,
            content=csv_content,
            branch=branch
        )
        
        print(f"[SUCCESS] Uploaded {filename} to GitHub successfully.")
        return True, filename
    except Exception as e:
        print(f"[ERROR] GitHub Push Failed: {e}")
        return False, str(e)
