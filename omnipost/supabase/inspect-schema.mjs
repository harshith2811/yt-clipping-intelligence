import pg from 'pg';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

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

async function run() {
  await client.connect();
  console.log('Connected to Supabase PostgreSQL!');

  // 1. List all public tables
  const tablesRes = await client.query(`
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name;
  `);
  console.log('\n--- Public Tables ---');
  for (const row of tablesRes.rows) {
    console.log(`- ${row.table_name}`);
  }

  // 2. Describe columns of will_submissions, submission_documents, profiles (if exists)
  for (const t of ['will_submissions', 'submission_documents', 'profiles', 'content_calendar']) {
    const cols = await client.query(`
      SELECT column_name, data_type, is_nullable, column_default
      FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = $1
      ORDER BY ordinal_position;
    `, [t]);
    if (cols.rows.length > 0) {
      console.log(`\n--- Columns for ${t} ---`);
      for (const c of cols.rows) {
        console.log(`  ${c.column_name}: ${c.data_type} (nullable: ${c.is_nullable}, default: ${c.column_default})`);
      }
    } else {
      console.log(`\n--- Table ${t} does not exist ---`);
    }
  }

  // 3. List RLS policies
  const polRes = await client.query(`
    SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
    FROM pg_policies
    WHERE schemaname = 'public'
    ORDER BY tablename, policyname;
  `);
  console.log('\n--- Existing RLS Policies in public ---');
  for (const p of polRes.rows) {
    console.log(`Table: ${p.tablename} | Policy: "${p.policyname}" | CMD: ${p.cmd} | Roles: ${p.roles}`);
    console.log(`  QUAL: ${p.qual}`);
    console.log(`  WITH CHECK: ${p.with_check}`);
  }

  // 4. List triggers on will_submissions and profiles
  const trigRes = await client.query(`
    SELECT event_object_table, trigger_name, event_manipulation, action_statement
    FROM information_schema.triggers
    WHERE trigger_schema = 'public'
    ORDER BY event_object_table, trigger_name;
  `);
  console.log('\n--- Triggers in public ---');
  for (const tr of trigRes.rows) {
    console.log(`Table: ${tr.event_object_table} | Trigger: ${tr.trigger_name} | Event: ${tr.event_manipulation}`);
  }

  // 5. Auth triggers on auth.users
  const authTrigRes = await client.query(`
    SELECT event_object_table, trigger_name, event_manipulation, action_statement
    FROM information_schema.triggers
    WHERE trigger_schema = 'auth'
    ORDER BY event_object_table, trigger_name;
  `);
  console.log('\n--- Triggers in auth ---');
  for (const tr of authTrigRes.rows) {
    console.log(`Table: ${tr.event_object_table} | Trigger: ${tr.trigger_name} | Event: ${tr.event_manipulation}`);
  }

  // 6. Check counts in auth.users and will_submissions
  const usersRes = await client.query(`SELECT id, email, created_at, raw_app_meta_data FROM auth.users;`);
  console.log(`\n--- auth.users (${usersRes.rows.length} users) ---`);
  for (const u of usersRes.rows) {
    console.log(`User: ${u.id} | Email: ${u.email} | Meta: ${JSON.stringify(u.raw_app_meta_data)}`);
  }

  const totalSubs = await client.query(`SELECT count(*) FROM will_submissions;`);
  console.log(`\n--- will_submissions: ${totalSubs.rows[0].count} total rows ---`);

  await client.end();
}

run().catch((err) => {
  console.error('Inspection failed:', err);
  process.exit(1);
});
