import { initializeApp, type FirebaseApp } from 'firebase/app'
import {
  getAuth,
  onAuthStateChanged as firebaseOnAuthStateChanged,
  signInWithEmailAndPassword,
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
