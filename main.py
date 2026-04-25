import json
from planner import generate_experiment_plan

hypothesis = """
Supplementing C57BL/6 mice with Lactobacillus rhamnosus GG for 4 weeks will
reduce intestinal permeability by at least 30% compared to controls, measured by
FITC-dextran assay, due to upregulation of tight junction proteins claudin-1 and occludin.
"""

if __name__ == "__main__":
    print("Generating experiment plan...\n")
    plan = generate_experiment_plan(hypothesis)
    
    print(f"Title: {plan['title']}")
    print(f"Summary: {plan['summary']}")
    print(f"\nTotal Budget: ${plan['budget']['total_usd']:,.2f}")
    print(f"Timeline: {plan['timeline']['total_weeks']} weeks")
    print(f"Materials count: {len(plan['materials']['items'])} items")
    print(f"Protocol phases: {len(plan['protocol']['phases'])}")
    
    # Save full output to file
    with open("output.json", "w") as f:
        json.dump(plan, f, indent=2)
    print("\nFull plan saved to output.json")