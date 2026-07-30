from github import Github
from datetime import datetime

def push_csv_to_github(csv_content, strategy_name, pat_token, repo_name, branch="main"):
    """
    Pushes the generated report CSV directly to a GitHub repository 
    under the 'output/' directory.
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_strat_name = strategy_name.lower().replace(" ", "_")
        
        # Ensures the file goes to the 'output' folder in the repo
        filepath = f"output/{clean_strat_name}_{timestamp}.csv"
        
        g = Github(pat_token)
        repo = g.get_repo(repo_name)
        commit_message = f"Add automated backtest results: {filepath}"
        
        repo.create_file(
            path=filepath,
            message=commit_message,
            content=csv_content,
            branch=branch
        )
        
        return True, filepath
    except Exception as e:
        return False, str(e)
