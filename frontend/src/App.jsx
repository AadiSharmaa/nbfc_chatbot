import React, { useState, useRef, useEffect, useCallback } from 'react';
import { RefreshCw, Send, Mic, HelpCircle, Paperclip, X, Square, Trash2, Volume2, VolumeX } from 'lucide-react';
import './App.css';

// API base URL — switch between local and deployed
// const API_BASE = 'http://localhost:8000';
const API_BASE = 'https://nbfc-ai-backend.onrender.com';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [hasStartedChat, setHasStartedChat] = useState(false);
  const [graphState, setGraphState] = useState(null);
  const [selectedImage, setSelectedImage] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [isRecording, setIsRecording] = useState(false);
  const [isTTSEnabled, setIsTTSEnabled] = useState(true);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [showForgetModal, setShowForgetModal] = useState(false);
  const [forgetPhone, setForgetPhone] = useState('');
  const [forgetStatus, setForgetStatus] = useState(null);

  // Session ID — persists across page refreshes within the same tab
  const [sessionId] = useState(() => {
    let id = sessionStorage.getItem('brisk_session_id');
    if (!id) {
      id = crypto.randomUUID();
      sessionStorage.setItem('brisk_session_id', id);
    }
    return id;
  });

  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const graphStateRef = useRef(graphState);
  const currentAudioRef = useRef(null);

  // Keep ref in sync for beforeunload handler
  useEffect(() => {
    graphStateRef.current = graphState;
  }, [graphState]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Save memory when tab/browser closes
  useEffect(() => {
    const handleUnload = () => {
      const state = graphStateRef.current;
      if (state?.customer_details?.phone) {
        const payload = JSON.stringify({
          chat_history: state.chat_history || [],
          customer_details: state.customer_details || {},
          phone_number: state.customer_details.phone
        });
        navigator.sendBeacon(`${API_BASE}/end-session`, payload);
      }
    };
    window.addEventListener('beforeunload', handleUnload);
    return () => window.removeEventListener('beforeunload', handleUnload);
  }, []);

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

  const stopCurrentAudio = () => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current.currentTime = 0;
      currentAudioRef.current = null;
      setIsSpeaking(false);
    }
  };

  const playTTS = async (text) => {
    if (!isTTSEnabled || !text) return;
    stopCurrentAudio();
    try {
      const response = await fetch(`${API_BASE}/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text })
      });

      if (!response.ok) return;

      const contentType = response.headers.get('content-type');
      if (!contentType || !contentType.includes('audio')) return;

      const audioBlob = await response.blob();
      const audioUrl = URL.createObjectURL(audioBlob);
      const audio = new Audio(audioUrl);
      currentAudioRef.current = audio;

      audio.onplay = () => setIsSpeaking(true);
      audio.onended = () => {
        setIsSpeaking(false);
        currentAudioRef.current = null;
        URL.revokeObjectURL(audioUrl);
      };
      audio.onerror = () => {
        setIsSpeaking(false);
        currentAudioRef.current = null;
        URL.revokeObjectURL(audioUrl);
      };

      await audio.play();
    } catch (err) {
      console.error('TTS playback error:', err);
      setIsSpeaking(false);
    }
  };

  const processAudio = async (audioBlob) => {
    setIsLoading(true);
    try {
      const formData = new FormData();
      formData.append("audio", audioBlob, "recording.webm");

      const response = await fetch(`${API_BASE}/transcribe`, {
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
    stopCurrentAudio();
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
      const response = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_input: textToSend,
          state: graphState || {},
          image: imageToSend,
          session_id: sessionId
        })
      });

      const data = await response.json();
      setMessages(prev => [...prev, { role: 'assistant', content: data.response }]);
      setGraphState(data.state);

      // Auto-play TTS for the assistant response
      playTTS(data.response);

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

  const resetChat = async () => {
    // Save conversation memory before clearing
    if (graphState?.customer_details?.phone) {
      try {
        await fetch(`${API_BASE}/end-session`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            chat_history: graphState.chat_history || [],
            customer_details: graphState.customer_details || {},
            phone_number: graphState.customer_details.phone
          })
        });
      } catch (err) {
        console.error('Failed to save session memory:', err);
      }
    }
    setMessages([]);
    setHasStartedChat(false);
    setGraphState(null);
    setInput('');
    clearImage();
    // Generate a new session ID for the next conversation
    const newId = crypto.randomUUID();
    sessionStorage.setItem('brisk_session_id', newId);
  };

  const handleForgetMe = async () => {
    if (!forgetPhone.trim() || forgetPhone.trim().length !== 10) {
      setForgetStatus({ type: 'error', message: 'Please enter a valid 10-digit phone number.' });
      return;
    }
    try {
      const response = await fetch(`${API_BASE}/forget-me`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone_number: forgetPhone.trim() })
      });
      const data = await response.json();
      setForgetStatus({ type: data.status === 'deleted' ? 'success' : 'info', message: data.message });
    } catch (err) {
      setForgetStatus({ type: 'error', message: 'Failed to connect to server.' });
    }
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
        <div className="header-actions">
          <button
            className={`icon-btn speaker-btn ${isTTSEnabled ? 'active' : ''}`}
            onClick={() => { if (isTTSEnabled) stopCurrentAudio(); setIsTTSEnabled(prev => !prev); }}
            title={isTTSEnabled ? 'Mute voice' : 'Enable voice'}
          >
            {isTTSEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
          </button>
          <button className="icon-btn forget-btn" onClick={() => { setShowForgetModal(true); setForgetStatus(null); setForgetPhone(''); }} title="Forget Me">
            <Trash2 size={18} />
          </button>
          <button className="icon-btn" onClick={resetChat} title="Reset Chat">
            <RefreshCw size={20} />
          </button>
        </div>
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
                <div className={`message-bubble ${msg.role === 'assistant' && isSpeaking && index === messages.length - 1 ? 'speaking' : ''}`}>
                  {renderMessageContent(msg.content)}
                  {msg.role === 'assistant' && isSpeaking && index === messages.length - 1 && (
                    <div className="speaking-indicator">
                      <span className="speaking-dot"></span>
                      <span className="speaking-dot"></span>
                      <span className="speaking-dot"></span>
                    </div>
                  )}
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

      {/* Forget Me Modal */}
      {showForgetModal && (
        <div className="modal-overlay" onClick={() => setShowForgetModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3><Trash2 size={20} /> Forget Me</h3>
              <button className="modal-close" onClick={() => setShowForgetModal(false)}>
                <X size={18} />
              </button>
            </div>
            <p className="modal-description">
              This will permanently delete all stored conversation memory associated with your phone number. This action cannot be undone.
            </p>
            <div className="modal-input-group">
              <input
                type="tel"
                className="modal-input"
                placeholder="Enter your 10-digit phone number"
                value={forgetPhone}
                onChange={(e) => setForgetPhone(e.target.value.replace(/\D/g, '').slice(0, 10))}
                maxLength={10}
              />
              <button className="modal-delete-btn" onClick={handleForgetMe}>
                Delete My Data
              </button>
            </div>
            {forgetStatus && (
              <div className={`modal-status ${forgetStatus.type}`}>
                {forgetStatus.message}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default App;