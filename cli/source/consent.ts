/**
 * OBP IMPLICIT consent creation.
 *
 * Creates role-specific consents by calling the OBP API directly,
 * matching what OBP-Portal does in /api/opey/consent.
 */

import {deduplicateRoles, pickConsentRole} from './roles.js';

export type ConsentResult = {
	consent_jwt: string;
	consent_id: string;
	status: string;
};

export type ConsentOptions = {
	obpBaseUrl: string;
	accessToken: string;
	opeyConsumerId: string;
	requiredRoles: string[];
	bankId?: string;
};

/**
 * Create an IMPLICIT consent for the given roles.
 *
 * 1. Fetches the user's current entitlements
 * 2. Deduplicates required roles (removes ones superseded by broader roles)
 * 3. Picks the best matching role the user actually holds
 * 4. Creates the consent via OBP API
 */
export async function createImplicitConsent(opts: ConsentOptions): Promise<ConsentResult> {
	const {obpBaseUrl, accessToken, opeyConsumerId, requiredRoles, bankId} = opts;
	const base = obpBaseUrl.replace(/\/$/, '');
	const headers = {
		'Content-Type': 'application/json',
		Authorization: `Bearer ${accessToken}`,
	};

	// 1. Fetch user's current entitlements
	const entRes = await fetch(`${base}/obp/v5.1.0/my/entitlements`, {headers});
	if (!entRes.ok) {
		const body = await entRes.text();
		throw new Error(`Failed to fetch entitlements (${entRes.status}): ${body}`);
	}

	const entData = (await entRes.json()) as {list?: Array<{role_name: string}>};
	const userRoleNames = (entData.list ?? []).map((e) => e.role_name);
	const userRolesSet = new Set(userRoleNames);

	// 2. Deduplicate required roles
	const deduped = deduplicateRoles(requiredRoles);

	// 3. Pick best matching role for each requirement
	const pickedRoles: string[] = [];
	const unsatisfiable: string[] = [];
	for (const role of deduped) {
		const picked = pickConsentRole(role, userRolesSet);
		if (picked === null) {
			unsatisfiable.push(role);
		} else {
			pickedRoles.push(picked);
		}
	}

	if (unsatisfiable.length > 0) {
		throw new Error(
			`Missing required roles: ${unsatisfiable.join(', ')}. You have: ${userRoleNames.join(', ') || '(none)'}`,
		);
	}

	// 4. Create IMPLICIT consent
	const now = new Date().toISOString().split('.')[0] + 'Z';
	const consentBody = {
		everything: false,
		entitlements: pickedRoles.map((roleName) => ({
			role_name: roleName,
			bank_id: bankId ?? '',
		})),
		consumer_id: opeyConsumerId,
		views: [],
		valid_from: now,
		time_to_live: 3600,
	};

	const consentRes = await fetch(`${base}/obp/v5.1.0/my/consents/IMPLICIT`, {
		method: 'POST',
		headers,
		body: JSON.stringify(consentBody),
	});

	if (!consentRes.ok) {
		const body = await consentRes.text();
		throw new Error(`Failed to create consent (${consentRes.status}): ${body}`);
	}

	const consent = (await consentRes.json()) as {
		jwt: string;
		consent_id: string;
		status: string;
	};

	return {
		consent_jwt: consent.jwt,
		consent_id: consent.consent_id,
		status: consent.status,
	};
}
