import pg from 'pg';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, '../.env') });

const { Client } = pg;
const client = new Client({
  host: process.env.SUPABASE_DB_HOST || 'aws-0-ap-northeast-2.pooler.supabase.com',
  port: parseInt(process.env.SUPABASE_DB_PORT || '5432', 10),
  user: process.env.SUPABASE_DB_USER || 'postgres.cmjhgvhtlpayjcrsqgox',
  password: (process.env.SUPABASE_DB_PASSWORD || '').replace(/^"|"$/g, ''),
  database: process.env.SUPABASE_DB_NAME || 'postgres',
  ssl: { rejectUnauthorized: false }
});

async function main() {
  await client.connect();
  console.log('Connected to Supabase PostgreSQL for migration application.');

  const migrationFile = path.join(__dirname, '001_client_auth_and_portal.sql');
  const sql = fs.readFileSync(migrationFile, 'utf8');

  console.log(`Executing migration: ${migrationFile}`);
  await client.query(sql);
  console.log('Migration 001 executed successfully!');

  // Verify created objects
  const tableCheck = await client.query(`
    SELECT table_name FROM information_schema.tables 
    WHERE table_schema = 'public' AND table_name IN ('profiles', 'consultations', 'will_submissions');
  `);
  console.log('Verified tables:', tableCheck.rows.map(r => r.table_name));

  const colCheck = await client.query(`
    SELECT column_name, data_type FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'will_submissions' AND column_name = 'user_id';
  `);
  console.log('Verified will_submissions.user_id:', colCheck.rows);

  const polCheck = await client.query(`
    SELECT tablename, policyname, cmd FROM pg_policies 
    WHERE schemaname = 'public'
    ORDER BY tablename, policyname;
  `);
  console.log('\nVerified Policies in public:');
  for (const p of polCheck.rows) {
    console.log(`- ${p.tablename}: "${p.policyname}" (${p.cmd})`);
  }

  await client.end();
}

main().catch((err) => {
  console.error('Migration failed:', err);
  process.exit(1);
});
