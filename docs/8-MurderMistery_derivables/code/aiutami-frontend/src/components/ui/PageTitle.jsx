export default function PageTitle({ children }) {
  return (
    <h1
      style={{
        fontSize: "1.8rem",
        color: "var(--text-dark)",
        marginBottom: "1.5rem",
        fontWeight: 700,
      }}
    >
      {children}
    </h1>
  );
}
