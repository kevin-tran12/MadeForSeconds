import { initializeApp, type FirebaseApp } from 'firebase/app'
import {
  getAuth,
  GoogleAuthProvider,
  onAuthStateChanged as firebaseOnAuthStateChanged,
  signInWithPopup,
  signInWithRedirect,
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

// Firebase error codes for "the popup never got a chance" — iOS Safari and
// some in-app browsers block or kill popups. Redirect-based sign-in lands the
// user back on this page with the session in place; onAuthChange picks it up.
const POPUP_BLOCKED_CODES = new Set([
  'auth/popup-blocked',
  'auth/operation-not-supported-in-this-environment',
  'auth/web-storage-unsupported',
])

/** Sign in with Google via popup, falling back to a full-page redirect where popups are blocked. */
export async function loginWithGoogle(): Promise<User | null> {
  const auth = getFirebaseAuth()
  const provider = new GoogleAuthProvider()
  try {
    const cred = await signInWithPopup(auth, provider)
    return cred.user
  } catch (err) {
    const code = (err as { code?: string } | null)?.code
    if (code && POPUP_BLOCKED_CODES.has(code)) {
      await signInWithRedirect(auth, provider)
      return null
    }
    throw err
  }
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

