import React, { useState } from 'react';
import styles from './App.module.css';

const App: React.FC = () => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.logo}>PokeTourney</div>
        <nav className={styles.nav}>
          <button className={styles.navLink}>Battle</button>
          <button className={styles.navLink}>Trainers</button>
          <button className={styles.navLink}>Login</button>
          <button className={styles.navLink}>Register</button>
        </nav>
        <button 
          className={styles.hamburger} 
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          aria-label="Toggle menu"
        >
          <span></span>
          <span></span>
          <span></span>
        </button>
        {mobileMenuOpen && (
          <div className={styles.mobileMenu}>
            <button className={styles.mobileNavLink} onClick={() => setMobileMenuOpen(false)}>Battle</button>
            <button className={styles.mobileNavLink} onClick={() => setMobileMenuOpen(false)}>Trainers</button>
            <button className={styles.mobileNavLink} onClick={() => setMobileMenuOpen(false)}>Login</button>
            <button className={styles.mobileNavLink} onClick={() => setMobileMenuOpen(false)}>Register</button>
          </div>
        )}
      </header>

      <div className={styles.heroSection}>
        <h1>Battle Legendary Trainers</h1>
        <p>Challenge gym leaders, Elite Four members, and champions from all Pokémon games. Test your team and climb the global leaderboard.</p>
        <div className={styles.ctaButtons}>
          <button>Start Battling</button>
          <button className={styles.secondary}>View All Trainers</button>
        </div>
      </div>

      <div className={styles.leaderboardSection}>
        <div className={styles.card}>
          <h2>Top 5 Trainers</h2>
          {leaderboardData.slice(0, 5).map((entry) => (
            <div key={entry.rank} className={styles.leaderboardItem}>
              <span className={styles.rank}>{entry.rank}</span>
              <span className={styles.trainerName}>{entry.name}</span>
              <span className={styles.trainerRating}>{entry.rating}</span>
            </div>
          ))}
        </div>

        <div className={styles.card}>
          <h2>Quick Stats</h2>
          <div className={styles.statsGrid}>
            {quickStats.map((stat) => (
              <div key={stat.label} className={styles.statItem}>
                <span className={styles.statLabel}>{stat.label}</span>
                <span className={styles.statValue}>{stat.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

const leaderboardData = [
  { rank: 1, name: 'Volo', rating: 2840 },
  { rank: 2, name: 'Cynthia', rating: 2756 },
  { rank: 3, name: 'Leon', rating: 2634 },
  { rank: 4, name: 'Sada', rating: 2532 },
  { rank: 5, name: 'Turo', rating: 2489 },
];

const quickStats = [
  { label: 'Total Battles', value: '12.5K' },
  { label: 'Most Battled Trainer', value: 'Volo' },
  { label: 'Avg Rating', value: '2156' },
  { label: 'Trainers', value: '180+' },
  { label: 'Regions', value: '9' },
];

export default App;