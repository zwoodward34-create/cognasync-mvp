import React, { useState, useEffect } from 'react';

export default function Trends() {
  const [trends, setTrends] = useState(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);

  useEffect(() => {
    const fetchTrends = async () => {
      try {
        const response = await fetch(`/api/trends?days=${days}`);
        if (response.ok) {
          const data = await response.json();
          setTrends(data);
        }
      } catch (error) {
        console.error('Error fetching trends:', error);
      } finally {
        setLoading(false);
      }
    };
    
    fetchTrends();
  }, [days]);

  if (loading) return <div>Loading trends...</div>;
  if (!trends) return <div>No trend data available</div>;

  return (
    <div style={{ padding: '20px' }}>
      <h2>Trends (Last {days} Days)</h2>
      
      <div style={{ marginBottom: '20px' }}>
        <button onClick={() => setDays(7)}>7 days</button>
        <button onClick={() => setDays(30)}>30 days</button>
        <button onClick={() => setDays(90)}>90 days</button>
      </div>

      <div style={{ marginBottom: '20px' }}>
        <h3>Check-ins: {trends.total_checkins}</h3>
        <p>Stability: {trends.average_stability}/10</p>
        <p>Dopamine: {trends.average_dopamine}/10</p>
        <p>Nervous System: {trends.average_nervous_system}/10</p>
        <p>Trend: {trends.trend_direction}</p>
      </div>

      {trends.current_medications && trends.current_medications.length > 0 && (
        <div>
          <h3>Current Medications</h3>
          <ul>
            {trends.current_medications.map(med => (
              <li key={med.id}>{med.name}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}