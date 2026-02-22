from psycopg2.pool import SimpleConnectionPool
import os
from typing import List, Dict, Optional

class Database:
    def __init__(self, database_url: str = None):
        if database_url is None:
            database_url = os.getenv('DATABASE_URL')

        if not database_url:
            raise ValueError(
                "DATABASE_URL environment variable is required. "
                "Please set it to your PostgreSQL connection string."
            )

        # Parse the database URL
        self.database_url = database_url

        # Initialize connection pool
        try:
            self.pool = SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=database_url
            )
            self.init_db()
        except Exception as e:
            raise Exception(f"Failed to connect to database: {e}")

    def get_connection(self):
        """Get a connection from the pool."""
        return self.pool.getconn()

    def put_connection(self, conn):
        """Return a connection to the pool."""
        self.pool.putconn(conn)

    def init_db(self):
        """Initialize the database with required tables."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()

            # Users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    is_admin INTEGER DEFAULT 0
                )
            ''')

            # Tasks table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id SERIAL PRIMARY KEY,
                    description TEXT NOT NULL,
                    assigned_to TEXT NOT NULL,
                    assigned_to_user_id BIGINT NOT NULL,
                    status TEXT DEFAULT 'open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_date TIMESTAMP,
                    created_by TEXT NOT NULL,
                    created_by_user_id BIGINT NOT NULL,
                    last_nudged_at TIMESTAMP
                )
            ''')

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            self.put_connection(conn)

    def add_user(self, user_id: int, username: str, is_admin: bool = False):
        """Add or update a user in the database."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (user_id, username, is_admin)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET username = EXCLUDED.username
            ''', (user_id, username, 1 if is_admin else 0))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            self.put_connection(conn)

    def is_admin(self, user_id: int) -> bool:
        """Check if a user is an admin."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT is_admin FROM users WHERE user_id = %s', (user_id,))
            result = cursor.fetchone()
            return result[0] == 1 if result else False
        finally:
            cursor.close()
            self.put_connection(conn)

    def grant_admin(self, user_id: int, username: str):
        """Grant admin privileges to a user."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (user_id, username, is_admin)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id)
                DO UPDATE SET username = EXCLUDED.username, is_admin = 1
            ''', (user_id, username))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            self.put_connection(conn)

    def create_task(self, description: str, assigned_to: str, assigned_to_user_id: int,
                    created_by: str, created_by_user_id: int) -> int:
        """Create a new task and return its ID."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO tasks (description, assigned_to, assigned_to_user_id,
                                 created_by, created_by_user_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING task_id
            ''', (description, assigned_to, assigned_to_user_id, created_by, created_by_user_id))
            task_id = cursor.fetchone()[0]
            conn.commit()
            return task_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            self.put_connection(conn)

    def get_user_tasks(self, user_id: int, status: str = None) -> List[Dict]:
        """Get tasks for a specific user."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()

            if status:
                cursor.execute('''
                    SELECT task_id, description, assigned_to, status, created_at,
                           completed_date, created_by, last_nudged_at
                    FROM tasks
                    WHERE assigned_to_user_id = %s AND status = %s
                    ORDER BY created_at DESC
                ''', (user_id, status))
            else:
                cursor.execute('''
                    SELECT task_id, description, assigned_to, status, created_at,
                           completed_date, created_by, last_nudged_at
                    FROM tasks
                    WHERE assigned_to_user_id = %s
                    ORDER BY created_at DESC
                ''', (user_id,))

            tasks = []
            for row in cursor.fetchall():
                tasks.append({
                    'task_id': row[0],
                    'description': row[1],
                    'assigned_to': row[2],
                    'status': row[3],
                    'created_at': row[4].isoformat() if row[4] else None,
                    'completed_date': row[5].isoformat() if row[5] else None,
                    'created_by': row[6],
                    'last_nudged_at': row[7].isoformat() if row[7] else None,
                })

            return tasks
        finally:
            cursor.close()
            self.put_connection(conn)

    def mark_task_completed(self, task_id: int, user_id: int) -> bool:
        """Mark a task as completed."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE tasks
                SET status = 'completed', completed_date = CURRENT_TIMESTAMP
                WHERE task_id = %s AND assigned_to_user_id = %s AND status = 'open'
            ''', (task_id, user_id))
            rows_affected = cursor.rowcount
            conn.commit()
            return rows_affected > 0
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            self.put_connection(conn)

    def get_all_open_tasks(self) -> List[Dict]:
        """Get all open tasks in the system."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT task_id, description, assigned_to, status, created_at,
                       created_by, last_nudged_at, assigned_to_user_id
                FROM tasks
                WHERE status = 'open'
                ORDER BY created_at ASC
            ''')

            tasks = []
            for row in cursor.fetchall():
                tasks.append({
                    'task_id': row[0],
                    'description': row[1],
                    'assigned_to': row[2],
                    'status': row[3],
                    'created_at': row[4].isoformat() if row[4] else None,
                    'created_by': row[5],
                    'last_nudged_at': row[6].isoformat() if row[6] else None,
                    'assigned_to_user_id': row[7]
                })

            return tasks
        finally:
            cursor.close()
            self.put_connection(conn)

    def get_task_by_id(self, task_id: int) -> Optional[Dict]:
        """Get a specific task by ID."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT task_id, description, assigned_to, assigned_to_user_id, status,
                       created_at, completed_date, created_by, created_by_user_id,
                       last_nudged_at
                FROM tasks
                WHERE task_id = %s
            ''', (task_id,))

            row = cursor.fetchone()

            if row:
                return {
                    'task_id': row[0],
                    'description': row[1],
                    'assigned_to': row[2],
                    'assigned_to_user_id': row[3],
                    'status': row[4],
                    'created_at': row[5].isoformat() if row[5] else None,
                    'completed_date': row[6].isoformat() if row[6] else None,
                    'created_by': row[7],
                    'created_by_user_id': row[8],
                    'last_nudged_at': row[9].isoformat() if row[9] else None,
                }
            return None
        finally:
            cursor.close()
            self.put_connection(conn)

    def update_nudge(self, task_id: int):
        """Update the last nudge time for a task."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE tasks
                SET last_nudged_at = CURRENT_TIMESTAMP
                WHERE task_id = %s
            ''', (task_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            self.put_connection(conn)

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Get user information by username."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, username, is_admin
                FROM users
                WHERE username = %s
            ''', (username,))

            row = cursor.fetchone()

            if row:
                return {
                    'user_id': row[0],
                    'username': row[1],
                    'is_admin': row[2] == 1
                }
            return None
        finally:
            cursor.close()
            self.put_connection(conn)

    def get_all_non_admin_users(self) -> List[Dict]:
        """Get all non-admin users for task assignment."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, username
                FROM users
                WHERE is_admin = 0
                ORDER BY username ASC
            ''')

            users = []
            for row in cursor.fetchall():
                users.append({
                    'user_id': row[0],
                    'username': row[1]
                })

            return users
        finally:
            cursor.close()
            self.put_connection(conn)

    def get_all_users_except(self, exclude_user_id: int) -> List[Dict]:
        """Get all users except the specified user."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, username, is_admin
                FROM users
                WHERE user_id != %s
                ORDER BY username ASC
            ''', (exclude_user_id,))

            users = []
            for row in cursor.fetchall():
                users.append({
                    'user_id': row[0],
                    'username': row[1],
                    'is_admin': row[2] == 1
                })

            return users
        finally:
            cursor.close()
            self.put_connection(conn)

    def get_todays_tasks(self) -> Dict[str, List[Dict]]:
        """Get a summary of today's tasks for the daily digest."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()

            # Get tasks created today
            cursor.execute('''
                SELECT task_id, description, assigned_to, created_at, created_by
                FROM tasks
                WHERE DATE(created_at) = CURRENT_DATE
                ORDER BY created_at DESC
            ''')
            created_today = []
            for row in cursor.fetchall():
                created_today.append({
                    'task_id': row[0],
                    'description': row[1],
                    'assigned_to': row[2],
                    'created_at': row[3].isoformat() if row[3] else None,
                    'created_by': row[4]
                })

            # Get tasks completed today
            cursor.execute('''
                SELECT task_id, description, assigned_to, completed_date, created_by
                FROM tasks
                WHERE DATE(completed_date) = CURRENT_DATE
                ORDER BY completed_date DESC
            ''')
            completed_today = []
            for row in cursor.fetchall():
                completed_today.append({
                    'task_id': row[0],
                    'description': row[1],
                    'assigned_to': row[2],
                    'completed_date': row[3].isoformat() if row[3] else None,
                    'created_by': row[4]
                })

            # Get all open tasks
            cursor.execute('''
                SELECT task_id, description, assigned_to, created_at, created_by
                FROM tasks
                WHERE status = 'open'
                ORDER BY created_at ASC
            ''')
            open_tasks = []
            for row in cursor.fetchall():
                open_tasks.append({
                    'task_id': row[0],
                    'description': row[1],
                    'assigned_to': row[2],
                    'created_at': row[3].isoformat() if row[3] else None,
                    'created_by': row[4]
                })

            return {
                'created_today': created_today,
                'completed_today': completed_today,
                'open_tasks': open_tasks
            }
        finally:
            cursor.close()
            self.put_connection(conn)

    def close(self):
        """Close all connections in the pool."""
        if self.pool:
            self.pool.closeall()
