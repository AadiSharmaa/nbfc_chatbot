import os
import re
import random
from typing import TypedDict, Literal, Dict, Any
from langgraph.graph import StateGraph, START, END
from groq import Groq
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------
# 1. API Configuration & LLM Setup
# ---------------------------------------------------------
load_dotenv()
API_KEY = os.getenv('groq_api_key')
client = Groq(api_key=API_KEY)
model_name = "llama-3.3-70b-versatile"

# ---------------------------------------------------------
# 2. State Definition & Database
# ---------------------------------------------------------
class GraphState(TypedDict):
    response: str
    customer_details: dict
    chat_history: list
    user_input: str
    active_agent: str
    expected_otp: str
    otp_verified: bool

CRM_DATABASE = {
    "6396605002": {
        "name": "Aadi Sharma",
        "city": "Dehradun",
        "address": "12, Marine Drive, Mumbai",
        "salary": 85000,
        "pre_approved_limit": 500000,
        "credit_score": 780
    },
    "9548788404": {
        "name": "Shivansh Kashyap",
        "city": "Delhi",
        "address": "45, Hauz Khas, New Delhi",
        "salary": 45000,
        "pre_approved_limit": 200000,
        "credit_score": 680
    }
}

def search_crm(phone_number):
    return CRM_DATABASE.get(phone_number)

# ---------------------------------------------------------
# 3. Agent Functions
# ---------------------------------------------------------
def ask_gemini(system_prompt, user_input, chat_history):
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(chat_history)
    messages.append({"role": "user", "content": user_input})

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.7
        )
        output_text = response.choices[0].message.content

        updated_history = chat_history.copy()
        updated_history.append({"role": "user", "content": user_input})
        updated_history.append({"role": "assistant", "content": output_text})

        return output_text, updated_history

    except Exception as e:
        return f"An error occurred: {e}", chat_history

def sales_agent(state: GraphState) -> GraphState:
    prompt = """You are a Sales Agent for an NBFC negotiating loan terms.
    Internal Checklist: Amount, Tenure, Purpose, Employment Type.
    CRITICAL: Never repeat questions. Acknowledge user input and ask ONLY for the missing items. Keep answers precise.

    HANDOFF RULE: Once you have collected ALL 4 items on your checklist, summarize the terms and EXPLICITLY ask the user to "please enter your 10-digit mobile number to proceed with KYC verification." """

    response_text, updated_history = ask_gemini(
        prompt,
        state['user_input'],
        state.get('chat_history', [])
    )
    return {**state,
            "response": response_text,
            "chat_history": updated_history,
            "active_agent": "sales"}

def verification_agent(state: GraphState) -> GraphState:
    user_input = state.get('user_input', '')
    expected_otp = state.get('expected_otp', '')
    customer_details = state.get('customer_details', {})

    if expected_otp:
        if re.search(r"\b" + re.escape(expected_otp) + r"\b", user_input):
            response_text = (
                f"KYC verified! Found details:\n"
                f"**Name:** {customer_details.get('name', 'N/A')}\n"
                f"**Address:** {customer_details.get('address', 'N/A')}\n"
                f"**Pre-approved Limit:** ₹{customer_details.get('pre_approved_limit', 'N/A')}\n\n"
                "Shall we proceed to the loan offer?"
            )
            return {**state, "response": response_text, "customer_details": customer_details,
                    "otp_verified": True, "expected_otp": "", "active_agent": "master"}
        else:
            return {**state, "response": "The OTP you entered does not match our records. Please try again.",
                    "active_agent": "verification"}

    phone_match = re.search(r"\b\d{10}\b", user_input)
    if phone_match:
        phone = phone_match.group(0)
        user_details = search_crm(phone)

        if user_details:
            otp = str(random.randint(1000, 9999))
            response_text = (
                f"Hi {user_details.get('name', '')}, we found your profile.\n"
                f"For KYC verification, a 4-digit OTP has been sent to **{phone}**.\n"
                f"*(Demo OTP: {otp})*\n\n"
                "Please type the OTP here to complete verification."
            )
            return {**state, "response": response_text, "customer_details": user_details,
                    "expected_otp": otp, "otp_verified": False, "active_agent": "verification"}
        else:
            return {**state, "response": "Verification Failed. This number is not in our records.",
                    "active_agent": "verification"}

    return {**state, "response": "To verify your identity, please enter your 10-digit mobile number.",
            "active_agent": "verification"}


def underwriting_agent(state: GraphState) -> GraphState:
    user_input = state.get('user_input', '')
    phone_match = re.search(r"\b\d{10}\b", user_input)

    if phone_match:
        phone_number = phone_match.group(0)
        user_data = search_crm(phone_number)
        if user_data:
            score = user_data.get("credit_score", 0)
            limit = user_data.get("pre_approved_limit", 0)
            loan_amount = user_data.get("loan_amount", 0) # Fallback to 0 if not set

            if score > 700 and limit >= loan_amount:
                return {**state, "response": "Loan approved", "active_agent": "underwriting"}
            elif score > 700 and limit < loan_amount:
                return {**state, "response": "Please provide your salary slip.", "active_agent": "underwriting"}
            else:
                return {**state, "response": "Loan rejected", "active_agent": "underwriting"}

    return {**state, "response": "Cannot underwrite without valid details.", "active_agent": "underwriting"}



def master_router(state: GraphState) -> Literal["sales_node", "verification_node", "exit"]:
    user_text = state.get("user_input", "").strip()

    if user_text.lower() == "done":
        return "exit"

    if re.search(r"\b\d{10}\b", user_text) or state.get("expected_otp"):
        return "verification_node"

    active_agent = state.get("active_agent", "master")
    chat_history = state.get("chat_history", [])

    last_assistant_msg = "None"
    if chat_history and len(chat_history) > 0:
        for msg in reversed(chat_history):
            if msg.get("role") == "assistant":
                last_assistant_msg = msg.get("content")
                break

    router_prompt = f"""You are a Master Routing Agent for an NBFC chatbot.
    Current Active Department: {active_agent.upper()}
    Assistant's Last Message: "{last_assistant_msg}"
    User's Latest Input: "{user_text}"

    ROUTING RULES:
    1. CONTEXTUAL CONTINUATION: If user input directly answers the Assistant's Last Message, route to Current Active Department.
    2. SALES: If user greets, asks about loan terms, interest rates, route to SALES.
    3. VERIFICATION: Route to VERIFICATION if user asks to submit KYC or provides a phone number.
    4. UNDERWRITING: After verification and negotiation the model need to approve or reject the loan offer.

    Respond with EXACTLY ONE WORD: SALES or VERIFICATION or UNDERWRITING.
    """
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": router_prompt}],
            temperature=0.0,
            max_tokens=10
        )
        decision = response.choices[0].message.content.strip().upper()
        return "verification_node" if "VERIFICATION" in decision else "sales_node"
    except Exception as e:
        print(f"Routing error: {e}")
        return f"{active_agent}_node" if active_agent in ["sales", "verification"] else "sales_node"

# ---------------------------------------------------------
# 4. Build LangGraph
# ---------------------------------------------------------
workflow = StateGraph(GraphState)
workflow.add_node("sales_node", sales_agent)
workflow.add_node("verification_node", verification_agent)
workflow.add_node("underwriting_node",underwriting_agent)

workflow.add_conditional_edges(
    START,
    master_router,
    {"sales_node": "sales_node",
    "verification_node": "verification_node",
    "underwriting_node": "underwriting_node",
    "exit": END
    }
)
workflow.add_edge("sales_node", END)
workflow.add_edge("verification_node", END)
workflow.add_edge("underwriting_node", END)
graph_app = workflow.compile()

# ---------------------------------------------------------
# 5. FastAPI Integration
# ---------------------------------------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    user_input: str
    state: Dict[str, Any]

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    current_state = req.state
    if not current_state:
        current_state = {
            "response": "",
            "customer_details": {},
            "chat_history": [],
            "user_input": "",
            "active_agent": "master",
            "expected_otp": "",
            "otp_verified": False
        }
    
    current_state["user_input"] = req.user_input
    result = graph_app.invoke(current_state)
    
    return {
        "response": result["response"],
        "state": result
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)