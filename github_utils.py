from github import Github
from datetime import datetime

def push_results_and_logs_to_github(csv_content, log_content, strategy_name, pat_token, repo_name, branch="main"):
    """
    Pushes BOTH the backtest results CSV and the full execution LOG text file 
    to the 'output/' folder in your GitHub repository.
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_name = strategy_name.lower().replace(" ", "_")
        
        csv_filepath = f"output/{clean_name}_{timestamp}_results.csv"
        log_filepath = f"output/{clean_name}_{timestamp}_execution.log"
        
        g = Github(pat_token)
        repo = g.get_repo(repo_name)
        
        # 1. Commit CSV Results
        repo.create_file(
            path=csv_filepath,
            message=f"Add backtest CSV output: {csv_filepath}",
            content=csv_content,
            branch=branch
        )
        
        # 2. Commit Full Execution Log
        repo.create_file(
            path=log_filepath,
            message=f"Add execution log: {log_filepath}",
            content=log_content,
            branch=branch
        )
        
        return True, f"Saved `{csv_filepath}` and `{log_filepath}`"
    except Exception as e:
        return False, str(e)
