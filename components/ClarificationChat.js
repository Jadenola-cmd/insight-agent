import { useRef, useState } from "react";

// Step0 问题澄清对话：用户与AI多轮对话，明确分析目标后进入文件上传
export default function ClarificationChat({ apiUrl, sessionId, onComplete }) {
  const [messages, setMessages] = useState([
    { role: "assistant", text: "您好，请简要描述一下这次想分析的业务问题（例如：想了解上月各渠道的销售下滑原因）。" },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const eventSourceRef = useRef(null);

  const startStream = () => {
    eventSourceRef.current?.close();
    const es = new EventSource(`${apiUrl}/api/clarify/${sessionId}/stream`);
    eventSourceRef.current = es;

    es.onmessage = (e) => {
      const payload = JSON.parse(e.data);
      if (payload.node === "clarification" && payload.data?.reply) {
        setMessages((prev) => [...prev, { role: "assistant", text: payload.data.reply }]);
      }
      if (payload.node === "clarification" && payload.status === "done" && payload.data?.analysis_goal) {
        es.close();
        onComplete?.(payload.data.analysis_goal);
      }
    };

    es.onerror = () => {
      es.close();
    };
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text) return;
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setSending(true);

    try {
      await fetch(`${apiUrl}/api/clarify/${sessionId}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      startStream();
    } catch (err) {
      // 接口未就绪时忽略错误，不阻塞演示流程
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="ia-card">
      <h2 style={styles.sectionTitle}>问题澄清</h2>
      <p style={styles.subtitle}>与 AI 简单对话，明确本次分析的目标与所需数据。</p>

      <div style={styles.chatBox}>
        {messages.map((m, idx) => (
          <div
            key={idx}
            style={m.role === "user" ? styles.bubbleUserRow : styles.bubbleAssistantRow}
          >
            <span style={m.role === "user" ? styles.bubbleUser : styles.bubbleAssistant}>
              {m.text}
            </span>
          </div>
        ))}
      </div>

      <div style={styles.inputRow}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="输入您的分析需求..."
          style={styles.input}
          disabled={sending}
        />
        <button className="btn btn-primary" onClick={handleSend} disabled={sending || !input.trim()}>
          发送
        </button>
      </div>

      <button className="btn btn-outline" onClick={() => onComplete?.()} style={{ marginTop: "1rem" }}>
        完成澄清，开始上传数据
      </button>
    </div>
  );
}

const styles = {
  sectionTitle: {
    margin: "0 0 0.3rem",
    fontSize: "1rem",
    fontWeight: 600,
    color: "#303133",
  },
  subtitle: {
    color: "#606266",
  },
  chatBox: {
    display: "flex",
    flexDirection: "column",
    gap: "0.5rem",
    maxHeight: "260px",
    overflowY: "auto",
    padding: "0.5rem 0",
  },
  bubbleAssistantRow: {
    display: "flex",
    justifyContent: "flex-start",
  },
  bubbleUserRow: {
    display: "flex",
    justifyContent: "flex-end",
  },
  bubbleAssistant: {
    backgroundColor: "#f4f4f5",
    color: "#303133",
    borderRadius: "0.6rem",
    padding: "0.5rem 0.8rem",
    maxWidth: "80%",
    fontSize: "0.9rem",
    lineHeight: 1.5,
  },
  bubbleUser: {
    backgroundColor: "#5470c6",
    color: "#fff",
    borderRadius: "0.6rem",
    padding: "0.5rem 0.8rem",
    maxWidth: "80%",
    fontSize: "0.9rem",
    lineHeight: 1.5,
  },
  inputRow: {
    display: "flex",
    gap: "0.5rem",
    marginTop: "0.5rem",
  },
  input: {
    flex: 1,
    padding: "0.45rem 0.7rem",
    borderRadius: "6px",
    border: "1px solid #dcdfe6",
    fontSize: "0.9rem",
    fontFamily: "inherit",
  },
};
