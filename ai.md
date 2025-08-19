# AI Instructions for Opey II

## Communication Style

- Be concise and direct
- Avoid excessive enthusiasm or chattiness
- Focus on technical facts and actionable information
- Use clear, professional language

## Logging Protocol

- Always update ai.log with commands run and results
- Add the LAST command or file executed at the end of ai.log
- Keep log entries brief and factual
- Include only essential information: command, result, next steps
- Use consistent formatting: command on one line, brief result/status below
- All ai.log entries must include date-time stamp in format: YYYY-MM-DD HH:MM:SS
- Log when starting major tasks in case of crashes (e.g. "Starting hardware mode test", "Beginning compilation", etc.)

## Log Message Format Standards

- Prepend each log message with "function_name says: " where function_name is the actual function making the log
- Remove all tick boxes, emojis, and other decorative characters from log messages
- Use plain text only for clarity and consistency

## Development Workflow

1. Check ai.log first to understand current project state
2. Run necessary commands/tests
3. Update ai.log with what was done
4. Provide concise summary to user

## Code Standards

- Prefer working solutions over perfect code
- Test changes incrementally
- Document significant findings in ai.log
