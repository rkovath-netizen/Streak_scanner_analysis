from github import Github
from datetime import datetime

def push_csv_to_github(csv_content, strategy_name, pat_token, repo_name, branch="main"):
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_name = strategy_name.lower().replace(" ", "_")
        filepath = f"output/{clean_name}_{timestamp}.csv"
        
        repo = Github(pat_token).get_repo(repo_name)
        repo.create_file(filepath, f"Add options backtest: {filepath}", csv_content, branch=branch)
        return True, filepath
    except Exception as e:
        return False, str(e)
