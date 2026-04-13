import os
import re
import random
import uuid
import datetime
from typing import TypedDict, Literal, Dict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from groq import Groq
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fpdf import FPDF
from memory import init_memory_db, get_conversation_summary, save_conversation_summary, delete_conversation_memory, summarize_conversation

# ---------------------------------------------------------
# 1. API Configuration & LLM Setup
# ---------------------------------------------------------
load_dotenv(find_dotenv())
API_KEY = os.getenv('groq_api_key') or os.getenv('GROQ_API_KEY')
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
    uploaded_image: str
    session_id: str
    memory_context: str

CRM_DATABASE = {
    "6396605002": {
        "name": "Aadi Sharma",
        "city": "Mumbai",
        "address": "12, Marine Drive, Mumbai",
        "salary": 85000,
        "pre_approved_limit": 500000,
        "credit_score": 780
    },
    "9548788404": {
        "name": "Shivansh Kashyap",
        "city": "Delhi",
        "address": "45, Hauz Khas, New Delhi",
        "salary": 55000,
        "pre_approved_limit": 250000,
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
    memory_ctx = state.get("memory_context", "")
    context_block = ""
    if memory_ctx:
        context_block = f"\n\nCONTEXT FROM PREVIOUS INTERACTIONS WITH THIS CUSTOMER:\n{memory_ctx}\nUse this context to personalize the conversation. Reference past interactions naturally (e.g., 'Welcome back!' or 'Last time you were looking at...'). Do NOT repeat the summary verbatim.\n"

    prompt = f"""You are a Sales Agent for an NBFC negotiating loan terms.
    Internal Checklist: Amount, Tenure, Purpose, Employment Type.
    {context_block}
    CONVERSATION GUIDELINES:
    1. RELEVANT QUESTIONS: If the user asks general questions about loans, interest rates, or banking, answer them openly and then gently guide the conversation back to collecting the missing checklist items.
    2. IRRELEVANT QUESTIONS: If the user asks about unrelated topics (e.g., cars, food, general chat), politely state that this is outside your expertise and steer them back to the loan application process.
    3. STRICT COMPLIANCE RULE: You MUST validate the 'Purpose'. Acceptable purposes are: Business Expansion, Medical Emergency, Education, Home Renovation, or Vehicle Purchase. If the user states ANY other purpose (like food, daily expenses, gambling, etc.), you MUST politely inform them that NBFC policy does not permit lending for this purpose. DO NOT ask for any more checklist items! Reject the loan immediately.
    4. CRITICAL: Never repeat questions. Acknowledge user input and ask ONLY for the missing items. Keep answers precise.

    HANDOFF RULE: Once you have collected ALL 4 items on your checklist AND the purpose is acceptable, summarize the terms and EXPLICITLY ask the user to \"please enter your 10-digit mobile number to proceed with KYC verification.\" """

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
                    "otp_verified": True, "expected_otp": "", "active_agent": "underwriting"}
        else:
            return {**state, "response": "The OTP you entered does not match our records. Please try again.",
                    "active_agent": "verification"}

    phone_match = re.search(r"\b\d{10}\b", user_input)
    if phone_match:
        phone = phone_match.group(0)
        user_details = search_crm(phone)

        if user_details:
            user_details = dict(user_details)
            user_details['phone'] = phone
            otp = str(random.randint(1000, 9999))

            # Load long-term memory for returning customers
            past_memory = get_conversation_summary(phone)
            memory_context = ""
            if past_memory:
                memory_context = past_memory["summary"]
                greeting_extra = f" Welcome back! This is interaction #{past_memory['interaction_count'] + 1}."
            else:
                greeting_extra = ""

            response_text = (
                f"Hi {user_details.get('name', '')}, we found your profile.{greeting_extra}\n"
                f"For KYC verification, a 4-digit OTP has been sent to **{phone}**.\n"
                f"*(Demo OTP: {otp})*\n\n"
                "Please type the OTP here to complete verification."
            )
            return {**state, "response": response_text, "customer_details": user_details,
                    "expected_otp": otp, "otp_verified": False, "active_agent": "verification",
                    "memory_context": memory_context}
        else:
            return {**state, "response": "Verification Failed. This number is not in our records.",
                    "active_agent": "verification"}

    return {**state, "response": "To verify your identity, please enter your 10-digit mobile number.",
            "active_agent": "verification"}


def generate_sanction_letter(user_data: dict, loan_amount: int, phone: str) -> str:
    """Generates a PDF sanction letter and returns its URL."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', size=16)

    # Title
    pdf.cell(200, 10, txt="SANCTION LETTER", ln=1, align='C')
    pdf.cell(200, 10, txt="", ln=1)

    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Date: {datetime.date.today()}", ln=1)
    pdf.cell(200, 10, txt=f"Name: {user_data.get('name', 'Customer')}", ln=1)
    pdf.cell(200, 10, txt=f"Address: {user_data.get('address', 'N/A')}", ln=1)
    pdf.cell(200, 10, txt=f"Phone: {phone}", ln=1)
    
    # Let's show either limit or requested loan amount. We'll show the limit if loan_amount falls back to 0.
    amount_to_show = loan_amount if loan_amount > 0 else user_data.get("pre_approved_limit", 0)
    pdf.cell(200, 10, txt=f"Approved Loan Amount: Rs. {amount_to_show}", ln=1)
    pdf.cell(200, 10, txt=f"Interest Rate: 12% p.a.", ln=1)
    pdf.cell(200, 10, txt=f"Processing Fees: 2% of loan amount + GST", ln=1)
    pdf.cell(200, 10, txt="", ln=1)
    
    body_text = (
        "Congratulations! We are pleased to inform you that your loan application "
        "has been conditionally approved under the terms and conditions outlined in our standard "
        "loan agreement."
    )
    pdf.multi_cell(0, 10, txt=body_text)

    # Save PDF
    os.makedirs("static/sanction_letters", exist_ok=True)
    filename = f"sanction_{phone}_{uuid.uuid4().hex[:6]}.pdf"
    filepath = os.path.join("static/sanction_letters", filename)
    pdf.output(filepath)

    return f"/static/sanction_letters/{filename}"

def verify_salary_slip(base64_img: str) -> int:
    prompt = "Analyze this salary slip image. Extract the monthly net or gross salary. Only output the numeric value of the monthly salary without any formatting. If no salary is found, output 0."
    try:
        if not base64_img.startswith("data:"):
            base64_img = f"data:image/jpeg;base64,{base64_img}"
            
        response = client.chat.completions.create(
            model="llama-3.2-90b-vision-preview",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": base64_img,
                            },
                        },
                    ],
                }
            ],
            temperature=0.0
        )
        output_text = response.choices[0].message.content.strip()
        match = re.search(r'\d[\d,]*', output_text)
        if match:
             return int(match.group().replace(',', ''))
    except Exception as e:
        print(f"Vision API error: {e}")
    return 0

def extract_loan_amount(chat_history: list) -> int:
    messages = [{"role": "system", "content": "Extract the requested loan amount in rupees from the conversation. Return ONLY the numeric value in digits (e.g., 1300000). Convert terms like 'lakh', 'k', 'thousand' to numbers correctly."}]
    
    recent_history = chat_history[-20:] if len(chat_history) > 20 else chat_history
    for msg in recent_history:
        messages.append({"role": msg.get("role", "user"), "content": str(msg.get("content", ""))})
        
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            temperature=0.0
        )
        output_text = response.choices[0].message.content.strip()
        match = re.search(r'\d[\d,]*', output_text)
        if match:
             return int(match.group().replace(',', ''))
    except Exception as e:
        print(f"Extraction error: {e}")
    return 0

def underwriting_agent(state: GraphState) -> GraphState:
    user_data = state.get('customer_details', {})
    
    if user_data and state.get('otp_verified'):
        phone_number = user_data.get("phone", "Unknown")
        score = user_data.get("credit_score", 0)
        limit = user_data.get("pre_approved_limit", 0)
        loan_amount = user_data.get("loan_amount", 0) # Fallback to 0 if not set
        
        if loan_amount == 0 and state.get("chat_history"):
            loan_amount = extract_loan_amount(state.get("chat_history"))
            user_data["loan_amount"] = loan_amount

        if score > 700 and limit >= loan_amount:
            pdf_url = generate_sanction_letter(user_data, loan_amount, phone_number)
            base_url = os.environ.get("RENDER_EXTERNAL_URL", os.environ.get("BASE_URL", "http://localhost:8000"))
            download_link = f"{base_url}{pdf_url}"
            response_msg = f"Loan approved! Your sanction letter is ready. You can download it here: {download_link}"
            return {**state, "response": response_msg, "active_agent": "underwriting"}
        elif score > 700 and limit < loan_amount:
            if state.get("uploaded_image"):
                salary_found = verify_salary_slip(state["uploaded_image"])
                if salary_found >= (loan_amount / 20):  # Assuming 20 months tenure tolerance or something similar, simple rule
                    # Approving dynamically based on slip
                    # Set limit to cover loan amount so it passes next time, or just approve inline
                    user_data["pre_approved_limit"] = loan_amount
                    pdf_url = generate_sanction_letter(user_data, loan_amount, phone_number)
                    base_url = os.environ.get("RENDER_EXTERNAL_URL", os.environ.get("BASE_URL", "http://localhost:8000"))
                    download_link = f"{base_url}{pdf_url}"
                    response_msg = f"Salary slip verified (Amount: Rs. {salary_found})! Loan conditionally approved based on verified salary. Your sanction letter is ready. You can download it here: {download_link}"
                    return {**state, "response": response_msg, "active_agent": "underwriting", "uploaded_image": "", "customer_details": user_data}
                else:
                    return {**state, "response": f"Loan rejected: Your verified salary (Rs. {salary_found}) is insufficient to support the requested loan amount of Rs. {loan_amount}.", "active_agent": "underwriting", "uploaded_image": ""}
            
            return {**state, "response": "Please provide your salary slip.", "active_agent": "underwriting"}
        else:
            reasons = []
            if score <= 700:
                reasons.append(f"Credit score ({score}) is below our minimum requirement of 700")
            reason_str = ", ".join(reasons) if reasons else "Does not meet our internal lending policies"
            return {**state, "response": f"Loan rejected: {reason_str}.", "active_agent": "underwriting"}

    return {**state, "response": "Cannot underwrite without valid details.", "active_agent": "underwriting"}



def master_router(state: GraphState) -> Literal["sales_node", "verification_node", "underwriting_node", "exit"]:
    user_text = state.get("user_input", "").strip()

    if user_text.lower() == "done":
        return "exit"

    if state.get("otp_verified") and state.get("active_agent") == "underwriting":
        positive_affirmations = ["yes", "proceed", "ok", "sure", "yeah", "yep", "do it"]
        if any(word in user_text.lower() for word in positive_affirmations):
            return "underwriting_node"

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

    memory_ctx = state.get("memory_context", "")
    memory_block = ""
    if memory_ctx:
        memory_block = f"\nPREVIOUS INTERACTION NOTES: {memory_ctx}\n"

    router_prompt = f"""You are a Master Routing Agent for an NBFC chatbot.
    Current Active Department: {active_agent.upper()}
    Assistant's Last Message: "{last_assistant_msg}"
    User's Latest Input: "{user_text}"
    {memory_block}
    COMPLIANCE MANDATE: Under no circumstances will you factor in the user's gender, caste, religion, or background when discussing loan terms, routing intents, or assessing risk.

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
        if "UNDERWRITING" in decision:
            return "underwriting_node"
        elif "VERIFICATION" in decision:
            return "verification_node"
        else:
            return "sales_node"
    except Exception as e:
        print(f"Routing error: {e}")
        if active_agent in ["sales", "verification", "underwriting"]:
            return f"{active_agent}_node"
        return "sales_node"

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

checkpoint_memory = MemorySaver()
graph_app = workflow.compile(checkpointer=checkpoint_memory)

# ---------------------------------------------------------
# 5. FastAPI Integration
# ---------------------------------------------------------
app = FastAPI()

# Initialize the long-term memory database on startup
init_memory_db()

if not os.path.exists("static/sanction_letters"):
    os.makedirs("static/sanction_letters")

app.mount("/static", StaticFiles(directory="static"), name="static")

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
    image: Optional[str] = None
    session_id: Optional[str] = None

class EndSessionRequest(BaseModel):
    chat_history: list
    customer_details: Dict[str, Any]
    phone_number: Optional[str] = None

class ForgetMeRequest(BaseModel):
    phone_number: str

@app.post("/transcribe")
async def transcribe_endpoint(audio: UploadFile = File(...)):
    try:
        content = await audio.read()
        filename = audio.filename if audio.filename else "audio.webm"
        # We ensure it has a recognized audio extension for whisper
        if not filename.endswith(('.mp3', '.mp4', '.mpeg', '.mpga', '.m4a', '.wav', '.webm')):
            filename = "audio.webm"
            
        transcription = client.audio.transcriptions.create(
          file=(filename, content),
          model="whisper-large-v3-turbo",
        )
        return {"text": transcription.text}
    except Exception as e:
        print(f"Transcription error: {e}")
        return {"error": str(e), "text": ""}

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
            "otp_verified": False,
            "session_id": "",
            "memory_context": ""
        }
    
    session_id = req.session_id or current_state.get("session_id") or str(uuid.uuid4())
    current_state["user_input"] = req.user_input
    current_state["session_id"] = session_id
    if req.image:
        current_state["uploaded_image"] = req.image

    # Invoke with thread_id for MemorySaver checkpointing
    config = {"configurable": {"thread_id": session_id}}
    result = graph_app.invoke(current_state, config=config)
    
    return {
        "response": result["response"],
        "state": result
    }


@app.post("/end-session")
async def end_session_endpoint(request: Request):
    """Summarize the conversation and save to long-term memory.
    Accepts both application/json (from fetch) and text/plain (from sendBeacon).
    """
    try:
        body = await request.json()
        phone_number = body.get("phone_number")
        chat_history = body.get("chat_history", [])
        customer_details = body.get("customer_details", {})

        if not phone_number:
            return {"status": "skipped", "reason": "No phone number provided"}

        summary = summarize_conversation(client, chat_history, customer_details)
        save_conversation_summary(phone_number, summary)
        return {"status": "saved", "summary": summary}
    except Exception as e:
        print(f"End-session error: {e}")
        return {"status": "error", "reason": str(e)}


@app.post("/forget-me")
async def forget_me_endpoint(req: ForgetMeRequest):
    """Delete all stored conversation memory for a phone number."""
    deleted = delete_conversation_memory(req.phone_number)
    if deleted:
        return {"status": "deleted", "message": f"All conversation memory for {req.phone_number} has been permanently deleted."}
    else:
        return {"status": "not_found", "message": f"No stored memory found for {req.phone_number}."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)