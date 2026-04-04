import React, { useState, useRef, useEffect } from 'react';
import { RefreshCw, Send, Mic, HelpCircle, Paperclip, X, Square } from 'lucide-react';
import './App.css';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [hasStartedChat, setHasStartedChat] = useState(false);
  const [graphState, setGraphState] = useState(null);
  const [selectedImage, setSelectedImage] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [isRecording, setIsRecording] = useState(false);

  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const promptCards = [
    { icon: '💼', text: 'I need a loan for my business' },
    { icon: '🏠', text: 'Apply for home loan' },
    { icon: '✅', text: 'Check my loan eligibility' },
    { icon: '📚', text: 'Education loan assistance' }
  ];

  const handleImageSelect = (e) => {
    const file = e.target.files[0];
    if (file) {
      const reader = new FileReader();
      reader.onloadend = () => {
        setSelectedImage(reader.result);
        setImagePreview(URL.createObjectURL(file));
      };
      reader.readAsDataURL(file);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const clearImage = () => {
    setSelectedImage(null);
    setImagePreview(null);
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        stream.getTracks().forEach(track => track.stop());
        await processAudio(audioBlob);
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error("Microphone access denied:", err);
      alert("Microphone access is required for voice input.");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const toggleRecording = () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  const processAudio = async (audioBlob) => {
    setIsLoading(true);
    try {
      const formData = new FormData();
      formData.append("audio", audioBlob, "recording.webm");

      const response = await fetch('https://nbfc-ai-backend.onrender.com/transcribe', {
      // const response = await fetch('http://localhost:8000/transcribe', {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();
      if (data.text && data.text.trim()) {
        handleSend(data.text);
      } else {
        setIsLoading(false);
      }
    } catch (error) {
      console.error("Transcription error:", error);
      setIsLoading(false);
    }
  };

  const handleSend = async (text) => {
    const userText = text || input;
    if (!userText.trim() && !selectedImage) return;

    setHasStartedChat(true);
    
    const contentToDisplay = userText + (selectedImage ? "\n[Attachment: Image]" : "");
    const userMessage = { role: 'user', content: contentToDisplay };
    setMessages(prev => [...prev, userMessage]);
    
    const textToSend = userText.trim() || (selectedImage ? "Here is my attached document." : "");
    const imageToSend = selectedImage;
    
    setInput('');
    clearImage();
    setIsLoading(true);

    try {
      // const response = await fetch('https://nbfc-ai-backend.onrender.com/chat', {  
      const response = await fetch('http://localhost:8000/chat' , {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_input: textToSend,
          state: graphState || {},
          image: imageToSend
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
    clearImage();
  };

  const renderMessageContent = (content) => {
    if (typeof content !== 'string') return content;
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    const parts = content.split(urlRegex);
    return parts.map((part, i) => {
      if (part.match(urlRegex)) {
        return <a key={i} href={part} target="_blank" rel="noopener noreferrer" style={{ color: '#007bff', textDecoration: 'underline', wordBreak: 'break-all' }}>{part}</a>;
      }
      return part;
    });
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
                  {renderMessageContent(msg.content)}
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
        {imagePreview && (
          <div className="image-preview-container">
            <img src={imagePreview} alt="Selected document" className="image-preview" />
            <button className="clear-image-btn" onClick={clearImage} title="Remove attachment">
              <X size={14} />
            </button>
          </div>
        )}
        <div className="input-box-wrapper">
          <div className="input-field-wrapper">
            <input 
              type="file" 
              accept="image/*" 
              ref={fileInputRef} 
              onChange={handleImageSelect} 
              style={{ display: 'none' }} 
            />
            <button className="attach-btn" onClick={() => fileInputRef.current?.click()} title="Attach salary slip">
              <Paperclip size={20} />
            </button>
            <input
              type="text"
              className="chat-input"
              placeholder="Message LoanAI"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            />
            <button 
              className={`send-btn ${(input.trim() || selectedImage) ? 'active' : ''}`}
              onClick={() => handleSend()}
              disabled={isLoading || (!input.trim() && !selectedImage)}
            >
              <Send size={18} />
            </button>
          </div>
          <button 
            className={`mic-btn ${isRecording ? 'recording' : ''}`}
            onClick={toggleRecording}
            title={isRecording ? "Stop recording" : "Voice input"}
          >
            {isRecording ? <Square size={20} fill="#ef4444" color="#ef4444" /> : <Mic size={20} />}
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