import { useRef, useState } from "react";

// Step7 追问对话：报告完成后支持继续追问，若需要补传数据则展示上传入口
export default function FollowupChat({ apiUrl, sessionId, onNeedMoreData }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [needMoreData, setNeedMoreData] = useState(false);
  const eventSourceRef = useRef(null);

  const startStream = () => {
    eventSourceRef.current?.close();
    const es = new EventSource(`${apiUrl}/api/analyze/${sessionId}/followup/stream`);
    eventSourceRef.current = es;

    es.onmessage = (e) => {
      const payload = JSON.parse(e.data);
      if (payload.node === "followup" && payload.data?.reply) {
        setMessages((prev) => [...prev, { role: "assistant", text: payload.data.reply }]);
      }
      if (payload.node === "followup" && payload.data?.need_more_data) {
        setNeedMoreData(true);
      }
      if (payload.node === "followup" && payload.status === "done") {
        es.close();
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
      await fetch(`${apiUrl}/api/analyze/${sessionId}/followup`, {
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
      <h2 style={styles.sectionTitle}>追问对话</h2>
      <p style={styles.subtitle}>对报告结论有疑问？可以继续追问，AI会基于现有数据补充分析。</p>

      {messages.length > 0 && (
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
      )}

      <div style={styles.inputRow}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="针对报告结论继续追问..."
          style={styles.input}
          disabled={sending}
        />
        <button className="btn btn-primary" onClick={handleSend} disabled={sending || !input.trim()}>
          发送
        </button>
      </div>

      {needMoreData && (
        <div style={styles.notice}>
          <p>本次追问需要补充新数据才能继续分析。</p>
          <button className="btn btn-outline" onClick={() => onNeedMoreData?.()}>
            前往补传数据
          </button>
        </div>
      )}
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
  notice: {
    marginTop: "1rem",
    padding: "0.8rem 1rem",
    borderRadius: "0.5rem",
    backgroundColor: "#fdf6ec",
    color: "#b88230",
  },
  noticeBtn: {
    marginTop: "0.5rem",
  },
};
