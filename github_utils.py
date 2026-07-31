from github import Github
from datetime import datetime

def push_csv_to_github(csv_content, strategy_name, pat_token, repo_name, branch="main"):
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_strat_name = strategy_name.lower().replace(" ", "_")
        
        # Writing directly to the 'output' folder in the GitHub repository
        file_path = f"output/{clean_strat_name}_{timestamp}.csv"
        
        g = Github(pat_token)
        repo = g.get_repo(repo_name)
        
        commit_message = f"Automated Backtest: {clean_strat_name} ({timestamp})"
        print(f"[DEBUG] Uploading to {repo_name}/{file_path}")
        
        repo.create_file(path=file_path, message=commit_message, content=csv_content, branch=branch)
        return True, file_path
    
    except Exception as e:
        print(f"[ERROR] GitHub Push Failed: {e}")
        return False, str(e)
