#!/usr/bin/env python3
''' Create Pull Request '''
import json
import os
import time
from git import Repo
from github import Github


def get_github_event(github_event_path):
    with open(github_event_path) as f:
        github_event = json.load(f)
    if bool(os.environ.get('DEBUG_EVENT')):
        print(os.environ['GITHUB_EVENT_NAME'])
        print(json.dumps(github_event, sort_keys=True, indent=2))
    return github_event


def ignore_event(event_name, event_data):
    if event_name == "push":
        # Ignore push events on deleted branches
        # The event we want to ignore occurs when a PR is created but the repository owner decides
        # not to commit the changes. They close the PR and delete the branch. This creates a 
        # "push" event that we want to ignore, otherwise it will create another branch and PR on
        # the same commit.
        deleted = "{deleted}".format(**event_data)
        if deleted == "True":
            print("Ignoring delete branch event.")
            return True
        ref = "{ref}".format(**event_data)
        if not ref.startswith('refs/heads/'):
            print("Ignoring events for tags and remotes.")
            return True
    return False


def pr_branch_exists(repo, branch):
    for ref in repo.remotes.origin.refs:
        if ref.name == ("origin/%s" % branch):
            return True
    return False


def get_head_author(event_name, event_data):
    if event_name == "push":
        email = "{head_commit[author][email]}".format(**event_data)
        name = "{head_commit[author][name]}".format(**event_data)
    else:
        email = os.environ['GITHUB_ACTOR'] + '@users.noreply.github.com'
        name = os.environ['GITHUB_ACTOR']
    return email, name


def get_head_short_sha1(repo):
    return repo.git.rev_parse('--short', 'HEAD')


def set_git_config(git, email, name):
    git.config('--global', 'user.email', '"%s"' % email)
    git.config('--global', 'user.name', '"%s"' % name)


def set_git_remote_url(git, token, github_repository):
    git.remote('set-url', 'origin', "https://x-access-token:%s@github.com/%s" % (token, github_repository))


def commit_changes(git, branch, commit_message):
    git.checkout('HEAD', b=branch)
    git.add('-A')
    git.commit(m=commit_message)
    return git.push('--set-upstream', 'origin', branch)


def create_pull_request(token, repo, head, base, title, body):
    return Github(token).get_repo(repo).create_pull(
        title=title,
        body=body,
        base=base,
        head=head)


def process_event(event_name, event_data, repo, branch, base):
    # Fetch required environment variables
    github_token = os.environ['GITHUB_TOKEN']
    github_repository = os.environ['GITHUB_REPOSITORY']
    # Fetch remaining optional environment variables
    commit_message = os.getenv(
        'COMMIT_MESSAGE',
        "Auto-committed changes by create-pull-request action")
    title = os.getenv(
        'PULL_REQUEST_TITLE',
        "Auto-generated by create-pull-request action")
    body = os.getenv(
        'PULL_REQUEST_BODY', "Auto-generated pull request by "
        "[create-pull-request](https://github.com/peter-evans/create-pull-request) GitHub Action")

    # Get the HEAD committer's email and name
    author_email, author_name = get_head_author(event_name, event_data)
    # Set git configuration
    set_git_config(repo.git, author_email, author_name)
    # Update URL for the 'origin' remote
    set_git_remote_url(repo.git, github_token, github_repository)

    # Commit the repository changes
    print("Committing changes.")
    commit_result = commit_changes(repo.git, branch, commit_message)
    print(commit_result)

    # Create the pull request
    print("Creating a request to pull %s into %s." % (branch, base))
    pull_request = create_pull_request(
        github_token,
        github_repository,
        branch,
        base,
        title,
        body
    )
    print("Created pull request %d." % pull_request.number)


# Get the JSON event data
event_name = os.environ['GITHUB_EVENT_NAME']
event_data = get_github_event(os.environ['GITHUB_EVENT_PATH'])
# Check if this event should be ignored
skip_ignore_event = bool(os.environ.get('SKIP_IGNORE'))
if skip_ignore_event or not ignore_event(event_name, event_data):
    # Set the repo to the working directory
    repo = Repo(os.getcwd())

    # Fetch/Set the branch name
    branch = os.getenv('PULL_REQUEST_BRANCH', 'create-pull-request/patch')
    # Set the current branch as the target base branch
    base = os.environ['GITHUB_REF'][11:]

    # Skip if the current branch is a PR branch created by this action
    if not base.startswith(branch):
        # Fetch an optional environment variable to determine the branch suffix
        branch_suffix = os.getenv('BRANCH_SUFFIX', 'short-commit-hash')
        if branch_suffix == "timestamp":
            # Suffix with the current timestamp
            branch = "%s-%s" % (branch, int(time.time()))
        else:
            # Suffix with the short SHA1 hash
            branch = "%s-%s" % (branch, get_head_short_sha1(repo))

        # Check if a PR branch already exists for this HEAD commit
        if not pr_branch_exists(repo, branch):
            # Check if there are changes to pull request
            if repo.is_dirty() or len(repo.untracked_files) > 0:
                print("Repository has modified or untracked files.")
                process_event(event_name, event_data, repo, branch, base)
            else:
                print("Repository has no modified or untracked files. Skipping.")
        else:
            print(
                "Pull request branch '%s' already exists for this commit. Skipping." %
                branch)
    else:
        print(
            "Branch '%s' was created by this action. Skipping." % base)
