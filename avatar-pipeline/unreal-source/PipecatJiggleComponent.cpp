#include "PipecatJiggleComponent.h"

#include "Components/SkeletalMeshComponent.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "HAL/IConsoleManager.h"

DEFINE_LOG_CATEGORY_STATIC(LogPipecatJiggle, Log, All);

namespace
{
TAutoConsoleVariable<int32> CVarEnable(TEXT("pipecat.Jiggle.Enable"), 1, TEXT("1 = jiggle physics on, 0 = off."));
TAutoConsoleVariable<float> CVarGain(TEXT("pipecat.Jiggle.Gain"), 1.0f,
	TEXT("Multiplies how much of the simulated motion is shown (1 = as simulated)."));
TAutoConsoleVariable<int32> CVarDebug(TEXT("pipecat.Jiggle.Debug"), 0, TEXT("1 = log the peak travel of each bone once a second."));

TAutoConsoleVariable<float> CVarBreastFreq(TEXT("pipecat.Jiggle.Breast.Freq"), 3.6f, TEXT("Breast spring frequency (Hz)."));
TAutoConsoleVariable<float> CVarBreastDamping(TEXT("pipecat.Jiggle.Breast.Damping"), 0.16f, TEXT("Breast damping ratio."));
TAutoConsoleVariable<float> CVarBreastMax(TEXT("pipecat.Jiggle.Breast.MaxCm"), 3.2f, TEXT("Breast maximum travel (cm)."));
TAutoConsoleVariable<float> CVarGluteFreq(TEXT("pipecat.Jiggle.Glute.Freq"), 3.0f, TEXT("Glute spring frequency (Hz)."));
TAutoConsoleVariable<float> CVarGluteDamping(TEXT("pipecat.Jiggle.Glute.Damping"), 0.26f, TEXT("Glute damping ratio."));
TAutoConsoleVariable<float> CVarGluteMax(TEXT("pipecat.Jiggle.Glute.MaxCm"), 2.2f, TEXT("Glute maximum travel (cm)."));

// Per-axis character of the motion in mesh space (X side to side, Y front to back, Z up and down): how stiff each axis
// is compared with the base frequency, and how far it may travel compared with the base maximum.
const FVector AxisFreq(1.15f, 0.95f, 1.0f);
const FVector AxisMax(0.65f, 0.85f, 1.0f);
constexpr float SimRate = 120.0f;  // minimum substeps per second
constexpr int32 MaxSubsteps = 24;
constexpr float TeleportDistance = 150.0f;

// Smooth limit: behaves like the identity for small values and saturates at +-Max.
FORCEINLINE float SoftLimit(float V, float Max)
{
	return Max > KINDA_SMALL_NUMBER ? Max * FMath::Tanh(V / Max) : 0.0f;
}
} // namespace

void UPipecatJiggleComponent::BeginPlay()
{
	Super::BeginPlay();

	ACharacter* Character = Cast<ACharacter>(GetOwner());
	Body = Character ? Character->GetMesh() : nullptr;
	if (!Body)
	{
		return;
	}

	static const TCHAR* Names[] = {TEXT("jiggle_breast_l"), TEXT("jiggle_breast_r"), TEXT("jiggle_glute_l"),
		TEXT("jiggle_glute_r")};
	for (const TCHAR* Name : Names)
	{
		FJiggleBone B;
		B.Name = FName(Name);
		B.Index = Body->GetBoneIndex(B.Name);
		B.bBreast = B.Name.ToString().Contains(TEXT("breast"));
		if (B.Index != INDEX_NONE)
		{
			Bones.Add(B);
		}
	}
	UE_LOG(LogPipecatJiggle, Log, TEXT("Jiggle physics on %d bone(s)%s"), Bones.Num(),
		Bones.Num() ? TEXT("") : TEXT(" (this mesh has no jiggle bones)"));
	if (Bones.Num())
	{
		FinalizedHandle = Body->RegisterOnBoneTransformsFinalizedDelegate(
			FOnBoneTransformsFinalizedMultiCast::FDelegate::CreateUObject(this, &UPipecatJiggleComponent::OnBonesFinalized));
	}
}

void UPipecatJiggleComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (Body && FinalizedHandle.IsValid())
	{
		Body->UnregisterOnBoneTransformsFinalizedDelegate(FinalizedHandle);
	}
	Super::EndPlay(EndPlayReason);
}

bool UPipecatJiggleComponent::GetAppliedOffset(FName BoneName, FVector& OutOffset) const
{
	if (!CVarEnable.GetValueOnGameThread())
	{
		return false;
	}
	for (const FJiggleBone& Bone : Bones)
	{
		if (Bone.Name == BoneName)
		{
			OutOffset = Bone.LastOffset * CVarGain.GetValueOnGameThread();
			return Bone.bInitialised;
		}
	}
	return false;
}

void UPipecatJiggleComponent::OnBonesFinalized()
{
	if (!Body || !Bones.Num() || !CVarEnable.GetValueOnGameThread() || !GetWorld())
	{
		return;
	}
	// Time since the previous pose update, measured in game time. (The frame delta is not safe here: the pose is not
	// necessarily updated exactly once per frame, and a wrong step makes the spring chase a wrong velocity.)
	const double Now = GetWorld()->GetTimeSeconds();
	const float Delta = LastSimTime < 0.0 ? 0.0f : FMath::Clamp(float(Now - LastSimTime), 0.0f, 0.05f);
	const bool bAdvance = Delta > 1e-4f;
	if (bAdvance || LastSimTime < 0.0)
	{
		LastSimTime = Now;
	}

	// The pose the renderer will read this frame (animation has just finished writing it).
	TArray<FTransform>& Pose = const_cast<TArray<FTransform>&>(Body->GetComponentSpaceTransforms());
	const FTransform CompToWorld = Body->GetComponentTransform();
	const float Gain = CVarGain.GetValueOnGameThread();

	for (FJiggleBone& Bone : Bones)
	{
		if (!Pose.IsValidIndex(Bone.Index))
		{
			continue;
		}
		const FVector Animated = Pose[Bone.Index].GetTranslation();
		const FVector Target = CompToWorld.TransformPosition(Animated);
		if (bAdvance || !Bone.bInitialised)
		{
			Step(Bone, CompToWorld, Target, bAdvance ? Delta : 1.0f / 60.0f);
		}
		const FVector Offset = Bone.LastOffset * Gain;
		Pose[Bone.Index].AddToTranslation(Offset);
		Bone.PeakCm = FMath::Max(Bone.PeakCm, Offset.Size());
	}

	if (CVarDebug.GetValueOnGameThread())
	{
		DebugTimer += Delta;
		if (DebugTimer >= 1.0f)
		{
			DebugTimer = 0.0f;
			for (FJiggleBone& Bone : Bones)
			{
				UE_LOG(LogPipecatJiggle, Log, TEXT("%-16s peak %.2f cm   now (%.2f %.2f %.2f)"), *Bone.Name.ToString(),
					Bone.PeakCm, Bone.LastOffset.X, Bone.LastOffset.Y, Bone.LastOffset.Z);
				if (Bone.DbgN)
				{
					UE_LOG(LogPipecatJiggle, Log, TEXT("   stats: avg dt %.4f s (%d updates)  anchor vel Y %.1f  particle vel Y %.1f  mean offset Y %.2f cm"),
						Bone.DbgDt / Bone.DbgN, Bone.DbgN, Bone.DbgTVy / Bone.DbgN, Bone.DbgVy / Bone.DbgN, Bone.DbgOffY / Bone.DbgN);
				}
				Bone.DbgDt = Bone.DbgTVy = Bone.DbgVy = Bone.DbgOffY = 0.0;
				Bone.DbgN = 0;
				Bone.PeakCm = 0.0f;
			}
		}
	}
}

void UPipecatJiggleComponent::Step(FJiggleBone& Bone, const FTransform& CompToWorld, FVector Target, float DeltaSeconds)
{
	const float Freq = Bone.bBreast ? CVarBreastFreq.GetValueOnGameThread() : CVarGluteFreq.GetValueOnGameThread();
	const float Zeta = Bone.bBreast ? CVarBreastDamping.GetValueOnGameThread() : CVarGluteDamping.GetValueOnGameThread();
	const float MaxCm = Bone.bBreast ? CVarBreastMax.GetValueOnGameThread() : CVarGluteMax.GetValueOnGameThread();

	if (!Bone.bInitialised || FVector::Dist(Target, Bone.PrevTarget) > TeleportDistance)
	{
		// first frame, or the character was teleported: start at rest on the animated position
		Bone.Pos = Target;
		Bone.Vel = FVector::ZeroVector;
		Bone.PrevTarget = Target;
		Bone.LastOffset = FVector::ZeroVector;
		Bone.bInitialised = true;
		return;
	}

	const FQuat Rot = CompToWorld.GetRotation();
	const FVector TargetVel = (Target - Bone.PrevTarget) / DeltaSeconds;
	const FVector Omega = AxisFreq * (2.0f * PI * Freq);                  // rad/s per axis
	const FVector MaxVec = AxisMax * MaxCm;
	const float TopOmega = FMath::Max3(Omega.X, Omega.Y, Omega.Z);
	// stay well inside the explicit integrator's stability limit, at any frame rate and any stiffness
	const int32 Steps = FMath::Clamp(FMath::CeilToInt(DeltaSeconds * FMath::Max(SimRate, TopOmega * 6.0f / PI)), 1, MaxSubsteps);
	const float H = DeltaSeconds / Steps;

	// Everything is done in the anchor's own frame: Dc is the particle's displacement from the animated bone and Vc its
	// velocity relative to the bone, both in mesh space. A moving anchor then only shows up where it should: as the
	// jump in relative velocity from one frame to the next (its acceleration, i.e. inertia).
	//
	// The spring itself stays LINEAR (so it can never gain energy). The smooth travel limit is applied only to what is
	// shown; internally there is just a loose safety stop at 4x the limit, which also kills the velocity pushing into it.
	FVector Dc = Rot.UnrotateVector(Bone.Pos - Bone.PrevTarget);
	FVector Vc = Rot.UnrotateVector(Bone.Vel - TargetVel);
	for (int32 i = 0; i < Steps; ++i)
	{
		const FVector Acc(-Omega.X * Omega.X * Dc.X - 2.0f * Zeta * Omega.X * Vc.X,
			-Omega.Y * Omega.Y * Dc.Y - 2.0f * Zeta * Omega.Y * Vc.Y,
			-Omega.Z * Omega.Z * Dc.Z - 2.0f * Zeta * Omega.Z * Vc.Z);
		Vc += Acc * H;                 // semi-implicit Euler: velocity first,
		Dc += Vc * H;                  // then displacement

		for (int32 Axis = 0; Axis < 3; ++Axis)
		{
			const float Stop = 4.0f * MaxVec[Axis];
			if (FMath::Abs(Dc[Axis]) > Stop)
			{
				Dc[Axis] = FMath::Sign(Dc[Axis]) * Stop;
				if (FMath::Sign(Vc[Axis]) == FMath::Sign(Dc[Axis]))
				{
					Vc[Axis] = 0.0f;
				}
			}
		}
	}
	Bone.Pos = Target + Rot.RotateVector(Dc);
	Bone.Vel = TargetVel + Rot.RotateVector(Vc);
	const FVector D(SoftLimit(Dc.X, MaxVec.X), SoftLimit(Dc.Y, MaxVec.Y), SoftLimit(Dc.Z, MaxVec.Z));

	Bone.DbgDt += DeltaSeconds;
	Bone.DbgTVy += Rot.UnrotateVector(TargetVel).Y;
	Bone.DbgVy += Rot.UnrotateVector(Bone.Vel).Y;
	Bone.DbgOffY += D.Y;
	++Bone.DbgN;
	Bone.PrevTarget = Target;
	Bone.LastOffset = D;   // mesh (component) space, centimetres
}
