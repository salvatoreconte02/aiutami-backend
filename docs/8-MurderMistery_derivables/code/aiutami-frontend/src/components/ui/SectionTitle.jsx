export default function SectionTitle({ children }) {
  return (
    <h2
      style={{
        fontSize: "1.4rem",
        color: "var(--primary)",
        marginBottom: "1rem",
        fontWeight: 600,
      }}
    >
      {children}
    </h2>
  );
}
