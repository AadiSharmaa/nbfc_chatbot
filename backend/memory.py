import sqlite3
import os
import datetime

# ---------------------------------------------------------
# Long-Term Memory Module
# Stores conversation summaries per phone number in SQLite.
# Summaries are APPENDED across sessions to build context.
# ---------------------------------------------------------

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.db")


def _get_connection():
    """Get a SQLite connection with row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_memory_db():
    """Create the conversation_memory table if it doesn't exist."""
    conn = _get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_memory (
                phone_number TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                interaction_count INTEGER DEFAULT 1
            )
        """)
        conn.commit()
    finally:
        conn.close()


def get_conversation_summary(phone_number: str) -> dict | None:
    """
    Retrieve the stored conversation summary for a phone number.
    Returns dict with 'summary', 'last_updated', 'interaction_count' or None.
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT summary, last_updated, interaction_count FROM conversation_memory WHERE phone_number = ?",
            (phone_number,)
        ).fetchone()
        if row:
            return {
                "summary": row["summary"],
                "last_updated": row["last_updated"],
                "interaction_count": row["interaction_count"]
            }
        return None
    finally:
        conn.close()


def save_conversation_summary(phone_number: str, new_summary: str):
    """
    Append a new conversation summary for a phone number.
    If a previous summary exists, the new summary is appended with a timestamp separator.
    """
    conn = _get_connection()
    try:
        existing = conn.execute(
            "SELECT summary, interaction_count FROM conversation_memory WHERE phone_number = ?",
            (phone_number,)
        ).fetchone()

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        if existing:
            # Append the new summary to the existing one
            old_summary = existing["summary"]
            count = existing["interaction_count"] + 1
            combined_summary = f"{old_summary}\n\n--- Session {count} ({now}) ---\n{new_summary}"

            conn.execute(
                "UPDATE conversation_memory SET summary = ?, last_updated = ?, interaction_count = ? WHERE phone_number = ?",
                (combined_summary, now, count, phone_number)
            )
        else:
            # First interaction — create new record
            combined_summary = f"--- Session 1 ({now}) ---\n{new_summary}"
            conn.execute(
                "INSERT INTO conversation_memory (phone_number, summary, last_updated, interaction_count) VALUES (?, ?, ?, 1)",
                (phone_number, combined_summary, now)
            )

        conn.commit()
    finally:
        conn.close()


def delete_conversation_memory(phone_number: str) -> bool:
    """
    Delete all stored conversation memory for a phone number.
    Returns True if a record was deleted, False if no record existed.
    """
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM conversation_memory WHERE phone_number = ?",
            (phone_number,)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def summarize_conversation(client, chat_history: list, customer_details: dict) -> str:
    """
    Use a small/fast LLM to generate a concise summary of the conversation.
    This summary is what gets stored in long-term memory.
    """
    if not chat_history:
        return "No conversation to summarize."

    # Build a condensed version of the chat for the summarizer
    conversation_text = ""
    for msg in chat_history:
        role = msg.get("role", "unknown").capitalize()
        content = msg.get("content", "")
        conversation_text += f"{role}: {content}\n"

    # Include customer details if available
    details_text = ""
    if customer_details:
        name = customer_details.get("name", "Unknown")
        phone = customer_details.get("phone", "Unknown")
        details_text = f"\nCustomer: {name} (Phone: {phone})"

    summarizer_prompt = f"""Summarize the following banking/loan conversation in 2-3 concise sentences.
Focus on: what the user wanted, any loan details discussed (amount, tenure, purpose), 
the outcome (approved/rejected/pending), and any notable context about the customer's situation.
Do NOT include any sensitive information like OTPs or passwords.
{details_text}

Conversation:
{conversation_text}

Summary:"""

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": summarizer_prompt}],
            temperature=0.3,
            max_tokens=200
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Summarization error: {e}")
        # Fallback: create a basic summary from available details
        if customer_details:
            return f"User {customer_details.get('name', 'Unknown')} had a conversation about loan services."
        return "User had a conversation about loan services."
