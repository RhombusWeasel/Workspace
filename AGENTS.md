# Instructions for Workspace Agents:

Your primary responsibilities are listed below:
 - ~/.agents/user.md This file exists to allow you to share information about the user between sessions to personalize the experience and allow for more meaningful responses.  Keep it up to date at all times as it is provided automatically in your system prompts.
 - .agents/design.md is a place for you to store information about the current repo you are working in.  This information is also provided in system prompts so should be kept up to date as a priority to ensure accuracy.
 - .agents/tasks.md is a place to track all of the tasks we have completed recently/have planned.  This information is also provided in system prompts so should be kept up to date as a priority to ensure accuracy.  It should contain filenames for the detailed plan documents stored in .agents/plans/.
 - Assist the user with their specific tasks using all of the skills and tools at your disposal.

You should always check for any design documentation files in the current working directory, design_document.md or README.md files to try and understand the project you are working on.
An early `ls -l | grep design` can save a lot of time reading other files trying to understand something that may be documented.

# Workflow for a change:

1. Search for design documentation and tasks to ascertain the changes required and present them to the user for confirmation.
2. Once the user has confirmed/clarified then add any modifications/updates to the task document so we can track our changes.
3. Create a plan, write a file to .agents/plans and add the filename to the task list so we can easily track it. Once the plan is complete then confirm with the user and ask any clarifying questions.  Any changes the user requests should be updated in the plan document before proceeding.
3. Make a branch for our changes so we can easily revert if we decide to change something after testing a feature.
4. Write the tests for the change.
5. Apply the change.
6. Ask the user to check and test the change.  Do not try and check the change yourself as the user may notice something you/they had not considered.

# Coding Principles:
1. Does this need to exist?   → no: skip it (YAGNI)
2. Already in this codebase?  → reuse it, don't rewrite
3. Stdlib does it?            → use it
4. Native platform feature?   → use it
5. Installed dependency?      → use it
6. One line?                  → one line
7. Only then: the minimum amount of code that works

# Skills
Below is an XML representation of the skills you have available, you can call the activate_skill tool at any time to get more detailed information about the skill and it's usage.
Skills are prefered over console commands where able as they can have additional access to various services etc.
You have the ability to create your own tools for whatever purpose is required by the user.  Use the activate_skill tool on 'workspace_docs' to get full details on how to expand your functionality.
