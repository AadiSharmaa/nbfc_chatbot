import React, { useState, useRef, useEffect } from 'react';
import { RefreshCw, Send, Mic, HelpCircle } from 'lucide-react';
import './App.css';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [hasStartedChat, setHasStartedChat] = useState(false);
  const [graphState, setGraphState] = useState(null);
  
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const promptCards = [
    { icon: '💼', text: 'I need a loan for my business' },
    { icon: '🏠', text: 'Apply for home loan' },
    { icon: '✅', text: 'Check my loan eligibility' },
    { icon: '📚', text: 'Education loan assistance' }
  ];

  const handleSend = async (text) => {
    const userText = text || input;
    if (!userText.trim()) return;

    setHasStartedChat(true);
    
    const userMessage = { role: 'user', content: userText };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await fetch('https://nbfc-ai-backend.onrender.com', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_input: userText,
          state: graphState || {} 
        })
      });

      const data = await response.json();
      setMessages(prev => [...prev, { role: 'assistant', content: data.response }]);
      setGraphState(data.state);
      
    } catch (error) {
      console.error("Backend connection error:", error);
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: "Sorry, I'm having trouble connecting to the server. Please make sure the Python backend is running." 
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const resetChat = () => {
    setMessages([]);
    setHasStartedChat(false);
    setGraphState(null);
    setInput('');
  };

  return (
    <div className="app-container">
      <header className="header">
        <div className="logo-container">
          <div className="logo-icon">💬</div>
          BriskAI
        </div>
        <button className="icon-btn" onClick={resetChat} title="Reset Chat">
          <RefreshCw size={20} />
        </button>
      </header>

      <main className="main-content">
        {!hasStartedChat ? (
          <div className="empty-state">
            <div className="glowing-orb"></div>
            
            <h1 className="greeting">Good evening, Aadi</h1>
            <h2 className="sub-greeting">What can I help you with?</h2>
            
            <p className="instruction-text">
              Choose a prompt below or write your own to start chatting with BriskAI
            </p>

            <div className="prompts-grid">
              {promptCards.map((card, index) => (
                <button 
                  key={index} 
                  className="prompt-card"
                  onClick={() => handleSend(card.text)}
                >
                  <span className="prompt-icon">{card.icon}</span>
                  <span>{card.text}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="chat-history">
            {messages.map((msg, index) => (
              <div key={index} className={`message-wrapper ${msg.role}`}>
                <div className="message-bubble">
                  {msg.content}
                </div>
              </div>
            ))}
            {isLoading && (
              <div className="message-wrapper assistant">
                <div className="message-bubble" style={{ color: '#9ca3af' }}>
                  BriskAI is typing...
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </main>

      <div className="input-container">
        <div className="input-box-wrapper">
          <div className="input-field-wrapper">
            <input
              type="text"
              className="chat-input"
              placeholder="Message LoanAI"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            />
            <button 
              className={`send-btn ${input.trim() ? 'active' : ''}`}
              onClick={() => handleSend()}
              disabled={isLoading || !input.trim()}
            >
              <Send size={18} />
            </button>
          </div>
          <button className="mic-btn">
            <Mic size={20} />
          </button>
        </div>
        <div className="footer-text">
          BriskAI can make mistakes. Please verify important information.
        </div>
      </div>

      <button className="help-fab">
        <HelpCircle size={24} />
      </button>
    </div>
  );
}

export default App;