import json
from claude_client import client, MODEL
from prompts import EXPERIMENT_PLAN_PROMPT, FEEDBACK_CONTEXT_TEMPLATE

def generate_experiment_plan(hypothesis: str, feedback: list = None) -> dict:
    
    feedback_context = ""
    if feedback:
        feedback_text = "\n".join([f"- {f}" for f in feedback])
        feedback_context = FEEDBACK_CONTEXT_TEMPLATE.format(feedback=feedback_text)
    
    prompt = EXPERIMENT_PLAN_PROMPT.format(
        hypothesis=hypothesis,
        feedback_context=feedback_context
    )
    
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    raw = response.content[0].text
    
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)