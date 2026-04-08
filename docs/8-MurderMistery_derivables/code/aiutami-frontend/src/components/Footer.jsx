export default function Footer() {
  const members = [
    { name: "Sara Imparato", img: "/team/member1.png" },
    { name: "Simone Cosenza", img: "/team/member2.jpg" },
    { name: "Salvatore Pio Conte", img: "/team/member3.jpg" },
  ];

  return (
    <footer
      style={{
        width: "100%",
        backgroundColor: "#f2f2f2",
        borderTop: "1px solid rgba(0,0,0,0.08)",
        fontFamily: "Arial, sans-serif",
        padding: "2.2rem 1.5rem",
      }}
    >
      {/* CONTENITORE CENTRALE DEL FOOTER */}
      <div
        style={{
          maxWidth: "1100px",
          margin: "0 auto",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          textAlign: "center",
          gap: "1.4rem",
        }}
      >
        {/* TESTO */}
        <div>
          <p
            style={{
              margin: 0,
              fontSize: "1rem",
              color: "#3C4653",
              fontWeight: "600",
            }}
          >
            © 2025-2026 <strong>AIutami</strong>
          </p>

          <p
            style={{
              margin: "0.6rem 0 0",
              fontSize: "0.9rem",
              color: "#6B7380",
              lineHeight: "1.5",
            }}
          >
            Realizzato da <strong>Sara Imparato</strong>, <strong>Simone Cosenza</strong> e{" "}
            <strong>Salvatore Pio Conte</strong>
            <br />
            per il progetto di <em>Advanced User Interface</em> — Politecnico di Milano
          </p>
        </div>

        {/* CONTENITORE MEMBRI (CENTRATO) */}
        <div
          style={{
            width: "100%",
            maxWidth: "720px",                 //controlla la “larghezza” del gruppo foto
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)", //3 colonne 
            gap: "2.5rem",
            justifyItems: "center",
            alignItems: "start",
          }}
        >
          {members.map((m) => (
            <div
              key={m.name}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: "0.6rem",
                width: "100%",
              }}
            >
              <img
                src={m.img}
                alt={m.name}
                style={{
                  width: "82px",
                  height: "82px",
                  borderRadius: "50%",
                  objectFit: "cover",
                  border: "2px solid rgba(0,0,0,0.18)",
                  backgroundColor: "#fff",
                }}
              />
              <div
                style={{
                  fontSize: "0.9rem",
                  color: "#2F3844",
                  fontWeight: "700",
                  textAlign: "center",
                  lineHeight: "1.2",
                }}
              >
                {m.name}
              </div>
            </div>
          ))}
        </div>
      </div>
    </footer>
  );
}
