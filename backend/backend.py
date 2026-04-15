import os
import io
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
from fastapi.responses import StreamingResponse
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

def extract_loan_amount_regex(chat_history: list) -> int:
    """Try to extract loan amount from chat text using regex patterns for Indian currency expressions."""
    # Combine all user messages into one text block
    user_text = " ".join(
        str(msg.get("content", "")) for msg in chat_history if msg.get("role") == "user"
    ).lower()
    
    # Also check assistant summaries (they often restate the amount clearly)
    all_text = " ".join(
        str(msg.get("content", "")) for msg in chat_history
    ).lower()

    # Pattern: "10 lakh", "10 lakhs", "10 lac", "10lakh", "₹10 lakh"
    lakh_match = re.search(r'[\₹rs\.?\s]*(\d+(?:\.\d+)?)\s*(?:lakh|lakhs|lac|lacs)\b', all_text)
    if lakh_match:
        return int(float(lakh_match.group(1)) * 100000)

    # Pattern: "10,00,000" or "1000000" (Indian notation for lakhs)
    indian_match = re.search(r'[\₹rs\.?\s]*(\d{1,2},\d{2},\d{3})', all_text)
    if indian_match:
        return int(indian_match.group(1).replace(',', ''))

    # Pattern: "500k", "500K"
    k_match = re.search(r'[\₹rs\.?\s]*(\d+(?:\.\d+)?)\s*k\b', all_text)
    if k_match:
        return int(float(k_match.group(1)) * 1000)

    # Pattern: "5 crore", "5 crores", "5 cr"
    crore_match = re.search(r'[\₹rs\.?\s]*(\d+(?:\.\d+)?)\s*(?:crore|crores|cr)\b', all_text)
    if crore_match:
        return int(float(crore_match.group(1)) * 10000000)

    # Pattern: plain large number like "1000000" or "500000"
    plain_match = re.search(r'[\₹rs\.?\s]*(\d{5,})', all_text)
    if plain_match:
        return int(plain_match.group(1))

    return 0

def extract_loan_amount(chat_history: list) -> int:
    """Extract the requested loan amount. Uses regex first (reliable), falls back to LLM."""
    # --- Step 1: Try regex-based extraction (fast and reliable) ---
    amount = extract_loan_amount_regex(chat_history)
    if amount > 0:
        print(f"[Loan Extraction] Regex found amount: {amount}")
        return amount

    # --- Step 2: Fallback to LLM extraction ---
    messages = [{"role": "system", "content": "Extract the requested loan amount in rupees from the conversation. Return ONLY the numeric value in digits (e.g., 1300000). Convert terms like 'lakh', 'k', 'thousand' to numbers correctly. If no loan amount is mentioned, return 0."}]
    
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
        print(f"[Loan Extraction] LLM returned: {output_text}")
        match = re.search(r'\d[\d,]*', output_text)
        if match:
             return int(match.group().replace(',', ''))
    except Exception as e:
        print(f"Extraction error: {e}")
    return 0

def calculate_emi(principal: int, annual_rate: float = 12.0, tenure_months: int = 60) -> float:
    """Calculate monthly EMI using the standard reducing balance formula."""
    monthly_rate = annual_rate / (12 * 100)
    if monthly_rate == 0:
        return principal / tenure_months
    emi = principal * monthly_rate * ((1 + monthly_rate) ** tenure_months) / (((1 + monthly_rate) ** tenure_months) - 1)
    return round(emi, 2)

def underwriting_agent(state: GraphState) -> GraphState:
    user_data = state.get('customer_details', {})
    user_text_lower = state.get("user_input", "").lower()
    
    if not (user_data and state.get('otp_verified')):
        return {**state, "response": "Cannot underwrite without valid KYC verification.", "active_agent": "underwriting"}

    # Handle negative response to conditional approval or document requests
    negative_affirmations = ["no", "nope", "cancel", "decline", "reject", "don't", "not"]
    if any(re.search(rf"\b{re.escape(word)}\b", user_text_lower) for word in negative_affirmations):
        return {
            **state,
            "response": "You have declined the offer or cancelled the process. Your application has been closed. Let us know if you need any other assistance in the future! Type 'done' to end the chat.",
            "active_agent": "master"
        }

    phone_number = user_data.get("phone", "Unknown")
    credit_score = user_data.get("credit_score", 0)
    salary = user_data.get("salary", 0)
    pre_limit = user_data.get("pre_approved_limit", None)

    # Extract loan amount
    loan_amount = user_data.get("loan_amount", 0)
    if loan_amount == 0 and state.get("chat_history"):
        loan_amount = extract_loan_amount(state.get("chat_history"))
        user_data["loan_amount"] = loan_amount

    if loan_amount <= 0:
        return {**state, "response": "Please specify the loan amount to proceed.", "active_agent": "underwriting"}

    # --- BASIC EMI CALCULATION ---
    emi = calculate_emi(loan_amount)
    
    base_url = os.environ.get("RENDER_EXTERNAL_URL", os.environ.get("BASE_URL", "http://localhost:8000"))

    # --- PRE-APPROVED LIMIT CONDITIONS ---
    if pre_limit and pre_limit > 0 and loan_amount <= pre_limit:
        # Condition 1: If requested amount is within pre-approved limit, approve immediately
        pdf_url = generate_sanction_letter(user_data, loan_amount, phone_number)
        download_link = f"{base_url}{pdf_url}"
        
        return {
            **state,
            "response": (
                f"✅ **Loan Approved!**\n\n"
                f"Your requested amount of ₹{loan_amount:,} is within your pre-approved limit.\n"
                f"EMI: ₹{emi:,.2f}/month\n\n"
                f"Download your sanction letter: {download_link}"
            ),
            "active_agent": "underwriting"
        }

    # Condition 2 & 3: Loan > pre-approved limit, or no limit available.
    # We must calculate risk score and require a salary slip upload.
    if not state.get("uploaded_image"):
        return {
            **state,
            "response": "To evaluate your requested loan amount, please upload your recent salary slip for income verification.",
            "active_agent": "underwriting"
        }

    if state.get("uploaded_image"):
        salary = verify_salary_slip(state["uploaded_image"])
        user_data["salary"] = salary
        state["uploaded_image"] = None  # Clear the image so it isn't looped

    if salary <= 0:
        return {
            **state,
            "response": "Unable to verify your income from the document. Please upload a clear, valid salary slip.",
            "active_agent": "underwriting"
        }

    # --- DTI Calculation ---
    dti = emi / salary  # debt-to-income ratio

    # --- HARD REJECTION RULES ---
    if credit_score < 650:
        return {
            **state,
            "response": f"❌ Loan Rejected: Credit score ({credit_score}) is below minimum threshold (650).",
            "active_agent": "underwriting"
        }

    if dti > 0.6:
        return {
            **state,
            "response": (
                f"❌ Loan Rejected:\n"
                f"Your EMI ₹{emi:,.2f} exceeds 60% of your monthly income ₹{salary:,}.\n"
                f"Please apply for a lower amount."
            ),
            "active_agent": "underwriting"
        }

    # --- RISK SCORING ---
    score = 0

    # Credit score weight (40%)
    if credit_score >= 750:
        score += 40
    elif credit_score >= 700:
        score += 30
    elif credit_score >= 650:
        score += 20

    # DTI weight (30%)
    if dti < 0.3:
        score += 30
    elif dti < 0.5:
        score += 20
    else:
        score += 10

    # Income strength (20%)
    if salary >= 100000:
        score += 20
    elif salary >= 50000:
        score += 15
    else:
        score += 10

    # Loan size vs income (10%)
    loan_to_income = loan_amount / (salary * 12)
    if loan_to_income < 0.5:
        score += 10
    elif loan_to_income < 1:
        score += 7
    else:
        score += 4

    # --- DECISION LOGIC ---
    base_url = os.environ.get("RENDER_EXTERNAL_URL", os.environ.get("BASE_URL", "http://localhost:8000"))

    # ✅ APPROVE
    if score >= 75:
        pdf_url = generate_sanction_letter(user_data, loan_amount, phone_number)
        download_link = f"{base_url}{pdf_url}"

        return {
            **state,
            "response": (
                f"✅ **Loan Approved!**\n\n"
                f"Risk Score: {score}/100\n"
                f"EMI: ₹{emi:,.2f}/month\n\n"
                f"Download your sanction letter: {download_link}"
            ),
            "active_agent": "underwriting"
        }

    # ⚠️ CONDITIONAL APPROVAL
    elif score >= 55:
        reduced_amount = int(loan_amount * 0.75)
        reduced_emi = calculate_emi(reduced_amount)

        return {
            **state,
            "response": (
                f"⚠️ **Conditional Approval**\n\n"
                f"Risk Score: {score}/100\n"
                f"The requested amount is slightly risky.\n\n"
                f"You are eligible for ₹{reduced_amount:,} instead.\n"
                f"New EMI: ₹{reduced_emi:,.2f}/month\n\n"
                f"Reply 'YES' to proceed with revised offer."
            ),
            "active_agent": "underwriting"
        }

    # ❌ REJECT
    else:
        return {
            **state,
            "response": (
                f"❌ **Loan Rejected**\n\n"
                f"Risk Score: {score}/100\n"
                f"Reason: High risk based on income, credit profile, and repayment capacity."
            ),
            "active_agent": "underwriting"
        }



def master_router(state: GraphState) -> Literal["sales_node", "verification_node", "underwriting_node", "exit"]:
    user_text = state.get("user_input", "").strip()

    if user_text.lower() == "done":
        return "exit"

    if state.get("uploaded_image"):
        return "underwriting_node"

    if state.get("otp_verified") and state.get("active_agent") == "underwriting":
        user_text_lower = user_text.lower()
        positive_affirmations = ["yes", "proceed", "ok", "sure", "yeah", "yep", "do it", "accept"]
        negative_affirmations = ["no", "nope", "cancel", "decline", "reject", "don't", "not"]
        
        if any(re.search(rf"\b{re.escape(word)}\b", user_text_lower) for word in positive_affirmations):
            return "underwriting_node"
            
        if any(re.search(rf"\b{re.escape(word)}\b", user_text_lower) for word in negative_affirmations):
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

class TTSRequest(BaseModel):
    text: str

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

@app.post("/tts")
async def tts_endpoint(req: TTSRequest):
    """Convert text to speech using Groq's TTS API and stream WAV audio back."""
    try:
        # Clean markdown formatting from text for cleaner speech
        clean_text = req.text
        clean_text = re.sub(r'\*\*(.*?)\*\*', r'\1', clean_text)  # Remove bold
        clean_text = re.sub(r'[\*\_\#\`]', '', clean_text)  # Remove other markdown
        clean_text = re.sub(r'https?://\S+', 'link provided', clean_text)  # Replace URLs
        clean_text = re.sub(r'[✅❌]', '', clean_text)  # Remove emojis that TTS can't speak
        clean_text = clean_text.strip()

        if not clean_text:
            return {"error": "No text to speak"}

        # Truncate very long text to avoid TTS timeouts
        if len(clean_text) > 1500:
            clean_text = clean_text[:1500] + '... and more details are shown in the chat.'

        response = client.audio.speech.create(
            model="canopylabs/orpheus-v1-english",
            voice="tara",
            input=clean_text,
            response_format="wav"
        )

        audio_bytes = response.read()
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/wav",
            headers={"Content-Length": str(len(audio_bytes))}
        )
    except Exception as e:
        print(f"TTS error: {e}")
        return {"error": str(e)}

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