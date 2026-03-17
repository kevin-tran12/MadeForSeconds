import { initializeApp, type FirebaseApp } from 'firebase/app'
import {
  getAuth,
  GoogleAuthProvider,
  onAuthStateChanged as firebaseOnAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  type Auth,
  type User,
} from 'firebase/auth'

let _app: FirebaseApp | null = null
let _auth: Auth | null = null

function getFirebaseAuth(): Auth {
  if (!_auth) {
    _app = initializeApp({
      apiKey: import.meta.env.VITE_FIREBASE_API_KEY as string,
      authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string,
      projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID as string,
    })
    _auth = getAuth(_app)
  }
  return _auth
}

export type AuthUser = User

export function initAuth() {
  // Force lazy init
  getFirebaseAuth()
}

export function onAuthChange(callback: (user: User | null) => void): () => void {
  const auth = getFirebaseAuth()
  return firebaseOnAuthStateChanged(auth, callback)
}

export async function login(email: string, password: string): Promise<User> {
  const auth = getFirebaseAuth()
  const cred = await signInWithEmailAndPassword(auth, email, password)
  return cred.user
}

export async function logout(): Promise<void> {
  const auth = getFirebaseAuth()
  await signOut(auth)
}

export async function getToken(): Promise<string | null> {
  const auth = getFirebaseAuth()
  const user = auth.currentUser
  if (!user) return null
  return user.getIdToken()
}

/**
 * Sign in with Google popup and return the user's email.
 * Used for supporter login — we only need the email to look up the subscription.
 */
export async function signInWithGoogle(): Promise<string> {
  const auth = getFirebaseAuth()
  const provider = new GoogleAuthProvider()
  const result = await signInWithPopup(auth, provider)
  const email = result.user.email
  if (!email) throw new Error('No email returned from Google')
  // Sign out of Firebase immediately — we don't need the Firebase session for supporters
  await signOut(auth)
  return email
}

export function isFirebaseConfigured(): boolean {
  return !!(import.meta.env.VITE_FIREBASE_API_KEY)
}
