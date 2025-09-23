import { useState, useEffect } from 'react';

interface Stats {
  failed_count: number;
  recovered_count: number;
  total_recovered_amount: number;
  recovery_percentage: number;
}

const StatCard = ({ title, value, prefix = '', suffix = '' }) => (
  <div className="bg-white shadow-lg rounded-xl p-6 text-center transform hover:scale-105 transition-transform duration-300">
    <h3 className="text-lg font-semibold text-gray-500">{title}</h3>
    <p className="text-4xl font-bold text-gray-800 mt-2">
      {prefix}{value}{suffix}
    </p>
  </div>
);

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = async () => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/stats';
      const apiKey = process.env.NEXT_PUBLIC_MERCHANT_API_KEY || '';
      const response = await fetch(apiUrl, { headers: { 'X-API-Key': apiKey } });
      if (!response.ok) throw new Error('Network response was not ok');
      const data: Stats = await response.json();
      setStats(data);
    } catch (err) {
      setError('Failed to fetch stats. Is the backend running/auth configured?');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
    const id = setInterval(fetchStats, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="min-h-screen bg-gray-100 font-sans">
      <header className="bg-white shadow-md">
        <div className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
          <h1 className="text-3xl font-bold text-gray-900">
            Re<span className="text-indigo-600">Cart</span> Recovery Dashboard
          </h1>
        </div>
      </header>

      <main className="max-w-7xl mx-auto py-10 px-4 sm:px-6 lg:px-8">
        {loading && <p className="text-center text-gray-500">Loading stats...</p>}
        {error && <p className="text-center text-red-500 bg-red-100 p-4 rounded-lg">{error}</p>}
        {stats && !loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <StatCard title="Failed Payments" value={stats.failed_count} />
            <StatCard title="Recovered Payments" value={stats.recovered_count} />
            <StatCard title="₹ Recovered" value={stats.total_recovered_amount.toFixed(2)} prefix="₹" />
            <StatCard title="Recovery Rate" value={stats.recovery_percentage.toFixed(2)} suffix="%" />
          </div>
        )}
      </main>
    </div>
  );
}
